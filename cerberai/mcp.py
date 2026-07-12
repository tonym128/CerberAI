import asyncio
import json
import os
import sys
import shutil
import subprocess
from typing import Dict, Any, List, Optional

class MCPClient:
    def __init__(self, name: str, command: str, args: List[str]):
        self.name = name
        self.command = command
        self.args = args
        self.process: Optional[asyncio.subprocess.Process] = None
        self.read_task: Optional[asyncio.Task] = None
        self.stderr_task: Optional[asyncio.Task] = None
        self.pending_requests: Dict[int, asyncio.Future] = {}
        self.next_id = 1
        self.tools: List[Dict[str, Any]] = []
        self._running = False

    async def start(self) -> bool:
        print(f"Starting MCP server '{self.name}': {self.command} {' '.join(self.args)}")
        try:
            resolved_cmd = shutil.which(self.command)
            if not resolved_cmd:
                if sys.platform == "win32" and not self.command.endswith(".cmd"):
                    resolved_cmd = shutil.which(f"{self.command}.cmd") or self.command
                else:
                    resolved_cmd = self.command

            # Prepare process startup arguments
            popen_args = {}
            if sys.platform == "win32":
                popen_args["creationflags"] = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

            self.process = await asyncio.create_subprocess_exec(
                resolved_cmd,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
                **popen_args
            )
            self._running = True
            self.read_task = asyncio.create_task(self._read_loop())
            self.stderr_task = asyncio.create_task(self._read_stderr_loop())
            
            # Perform MCP Handshake
            await self._initialize()
            return True
        except Exception as e:
            print(f"Failed to start MCP server '{self.name}': {e}")
            self._running = False
            return False

    async def _initialize(self):
        # 1. Send 'initialize'
        init_res = await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "cerberai-host",
                "version": "0.1.0"
            }
        })
        # 2. Send 'initialized' notification (no response expected)
        await self.send_notification("notifications/initialized", {})
        print(f"MCP server '{self.name}' initialized successfully.")

    async def list_tools(self) -> List[Dict[str, Any]]:
        try:
            res = await self.send_request("tools/list", {})
            self.tools = res.get("tools", [])
            return self.tools
        except Exception as e:
            print(f"Failed to list tools for MCP server '{self.name}': {e}")
            return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        try:
            res = await self.send_request("tools/call", {
                "name": name,
                "arguments": arguments
            })
            return res
        except Exception as e:
            print(f"Error calling tool '{name}' on MCP '{self.name}': {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    async def send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._running or not self.process or not self.process.stdin:
            raise Exception("MCP server is not running.")
            
        req_id = self.next_id
        self.next_id += 1
        
        future = asyncio.get_running_loop().create_future()
        self.pending_requests[req_id] = future
        
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id
        }
        
        message = json.dumps(req) + "\n"
        self.process.stdin.write(message.encode("utf-8"))
        await self.process.stdin.drain()
        
        try:
            return await future
        finally:
            self.pending_requests.pop(req_id, None)

    async def send_notification(self, method: str, params: Dict[str, Any]):
        if not self._running or not self.process or not self.process.stdin:
            return
            
        req = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        
        message = json.dumps(req) + "\n"
        self.process.stdin.write(message.encode("utf-8"))
        await self.process.stdin.drain()

    async def _read_loop(self):
        buffer = bytearray()
        while self._running and self.process and self.process.stdout:
            try:
                # Read chunks of data to support arbitrarily large responses
                chunk = await self.process.stdout.read(8192)
                if not chunk:
                    break
                
                buffer.extend(chunk)
                
                while b'\n' in buffer:
                    line_bytes, remaining = buffer.split(b'\n', 1)
                    buffer = bytearray(remaining)
                    
                    if not line_bytes:
                        continue
                        
                    # Parse JSON-RPC message
                    msg = json.loads(line_bytes.decode("utf-8"))
                    
                    # Handle Response
                    if "id" in msg and ("result" in msg or "error" in msg):
                        req_id = msg["id"]
                        future = self.pending_requests.get(req_id)
                        if future and not future.done():
                            if "error" in msg:
                                future.set_exception(Exception(msg["error"].get("message", "Unknown error")))
                            else:
                                future.set_result(msg["result"])
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in MCP client read loop for '{self.name}': {e}")
                await asyncio.sleep(0.1)

    async def _read_stderr_loop(self):
        while self._running and self.process and self.process.stderr:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                print(f"[{self.name} STDERR] {line.decode('utf-8').strip()}")
            except Exception:
                break

    async def stop(self):
        self._running = False
        if self.read_task:
            self.read_task.cancel()
        if self.stderr_task:
            self.stderr_task.cancel()
            
        if self.process:
            try:
                self.process.terminate()
                await self.process.wait()
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.process = None


class MCPManager:
    def __init__(self, config_servers: Dict[str, Any]):
        self.config_servers = config_servers
        self.clients: Dict[str, MCPClient] = {}

    async def start_all(self):
        if not self.config_servers:
            return
        tasks = []
        for name, cfg in self.config_servers.items():
            command = cfg.get("command")
            args = cfg.get("args", [])
            if not command:
                continue
            client = MCPClient(name, command, args)
            self.clients[name] = client
            tasks.append(client.start())
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, res in zip(self.clients.keys(), results):
            if isinstance(res, Exception) or not res:
                print(f"MCP server '{name}' failed to boot.")
                self.clients.pop(name, None)
            else:
                # Cache list of tools
                await self.clients[name].list_tools()

    async def get_all_tools(self) -> List[Dict[str, Any]]:
        all_tools = []
        for client_name, client in self.clients.items():
            for t in client.tools:
                tool_copy = dict(t)
                tool_copy["server_name"] = client_name
                all_tools.append(tool_copy)
        return all_tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        client = self.clients.get(server_name)
        if not client:
            return {"content": [{"type": "text", "text": f"Error: MCP Server '{server_name}' not running."}], "isError": True}
        return await client.call_tool(tool_name, arguments)

    async def stop_all(self):
        tasks = [client.stop() for client in self.clients.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.clients.clear()
