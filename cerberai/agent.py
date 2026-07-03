import os
import re
import json
import asyncio
import importlib.util
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
import httpx
from .config import AppConfig

# Simple decorator for python tools
def tool(name: str, description: str):
    def decorator(func):
        func.is_tool = True
        func.tool_name = name
        func.tool_description = description
        return func
    return decorator

class AgentExecutor:
    def __init__(self, config: AppConfig):
        self.config = config
        self.tools: Dict[str, Any] = {}
        self.mcp_servers: Dict[str, Any] = {}
        
        # 1. Register Built-in Tools
        self.register_builtin_tools()
        
        # 2. Load Local Skills as Tools
        self.load_skills()

    def register_builtin_tools(self):
        """Register default tools like Web Search."""
        self.tools["web_search"] = {
            "name": "web_search",
            "description": "web_search(query: str) - Search the web for information using DuckDuckGo.",
            "func": self.web_search_tool
        }
        self.tools["web_fetch"] = {
            "name": "web_fetch",
            "description": "web_fetch(url: str) - Fetch the clean readable text content of a specific web page/URL.",
            "func": self.web_fetch_tool
        }

    async def web_fetch_tool(self, url: str) -> str:
        """Fetch the content of a specific web page and return the stripped clean text."""
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }
        try:
            # Add protocol prefix if missing
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return f"Error: Failed to fetch page. HTTP Status Code {response.status_code}"
                
                html_content = response.text
                
                # Strip style and script elements completely
                html_content = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                html_content = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                
                # Strip all other HTML tags
                import html
                text = re.sub(r'<[^>]+>', ' ', html_content)
                
                # Unescape HTML entities
                text = html.unescape(text)
                
                # Normalize whitespace
                lines = [line.strip() for line in text.splitlines()]
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean_text = "\n".join(chunk for chunk in chunks if chunk)
                
                # Truncate content to avoid exceeding context window
                limit = 15000
                if len(clean_text) > limit:
                    return clean_text[:limit] + f"\n\n... (Content truncated: {len(clean_text) - limit} characters remaining)"
                
                if not clean_text.strip():
                    return "Page fetched successfully, but no readable text content was found."
                
                return clean_text
        except Exception as e:
            return f"Fetch error: {e}"

    async def web_search_tool(self, query: str) -> str:
        """Query DuckDuckGo HTML search page and parse top results, falling back to Wikipedia if blocked."""
        import html
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }
        try:
            async with httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True) as client:
                response = await client.get(url)
                
                # Check if we got a valid non-blocked page
                if response.status_code == 200 and "anomaly-modal" not in response.text:
                    html_content = response.text
                    
                    titles = re.findall(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', html_content, re.DOTALL)
                    snippets = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html_content, re.DOTALL)
                    raw_links = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"', html_content, re.DOTALL)
                    
                    results = []
                    for i, (title, snippet, raw_link) in enumerate(zip(titles[:5], snippets[:5], raw_links[:5])):
                        clean_title = html.unescape(re.sub(r'<[^>]+>', '', title).strip())
                        clean_snippet = html.unescape(re.sub(r'<[^>]+>', '', snippet).strip())
                        
                        # Resolve actual URL from uddg param
                        real_url = raw_link
                        if "uddg=" in raw_link:
                            match = re.search(r'uddg=([^&]+)', raw_link)
                            if match:
                                real_url = urllib.parse.unquote(match.group(1))
                        
                        results.append(f"{i+1}. {clean_title}\nSnippet: {clean_snippet}\nSource: {real_url}\n")
                        
                    if results:
                        return "\n".join(results)

                # Fallback 1: Try DuckDuckGo Instant Answer API first (no CAPTCHA)
                print("DuckDuckGo HTML search challenge encountered. Trying DuckDuckGo Instant Answer API...")
                ddg_api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json"
                try:
                    async with httpx.AsyncClient(timeout=10.0) as api_client:
                        api_res = await api_client.get(ddg_api_url)
                        if api_res.status_code in (200, 202):
                            api_data = api_res.json()
                            api_results = []
                            abstract = api_data.get("AbstractText", "")
                            if abstract:
                                source_name = api_data.get("AbstractSource", "DuckDuckGo")
                                source_url = api_data.get("AbstractURL", "")
                                api_results.append(f"1. Abstract Summary: {abstract}\nSource: {source_url} ({source_name})\n")
                            
                            # Append related topics
                            related = api_data.get("RelatedTopics", [])
                            count = 0
                            for item in related:
                                if count >= 4:
                                    break
                                text = item.get("Text")
                                url = item.get("FirstURL")
                                if text and url:
                                    api_results.append(f"{len(api_results)+1}. {text}\nSource: {url}\n")
                                    count += 1
                                    
                            if api_results:
                                return "\n".join(api_results)
                except Exception as api_err:
                    print(f"DuckDuckGo Instant Answer API check failed: {api_err}")

                # Fallback 2: Wikipedia API search if DuckDuckGo triggers CAPTCHA or errors
                print("Falling back to Wikipedia API...")
                wiki_api_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json"
                wiki_headers = {
                    "User-Agent": "CerberAI/1.0 (tonym@example.com)"
                }
                async with httpx.AsyncClient(headers=wiki_headers, timeout=10.0) as wiki_client:
                    wiki_res = await wiki_client.get(wiki_api_url)
                    if wiki_res.status_code == 200:
                        data = wiki_res.json()
                        search_results = data.get("query", {}).get("search", [])
                        results = []
                        for idx, r in enumerate(search_results[:5]):
                            title = r.get("title", "")
                            snippet = html.unescape(re.sub(r'<[^>]+>', '', r.get("snippet", "")).strip())
                            page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                            results.append(f"{idx+1}. {title}\nSnippet: {snippet}\nSource: {page_url}\n")
                        if results:
                            return "\n".join(results)
                            
                return "Error: Search challenge encountered and all fallbacks (DuckDuckGo Instant Answer & Wikipedia) returned no results."
        except Exception as e:
            return f"Search error: {e}"

    def load_skills(self):
        """Scan skills directory and dynamically import any registered python tools."""
        skills_paths = [
            Path(os.path.expanduser("~/.gemini/config/skills")),
            Path(".agents/skills")
        ]
        for path in skills_paths:
            if not path.exists():
                continue
            
            for skill_dir in path.iterdir():
                if not skill_dir.is_dir():
                    continue
                
                # Check for python files containing tools
                for py_file in skill_dir.glob("**/*.py"):
                    try:
                        spec = importlib.util.spec_from_file_location(py_file.stem, str(py_file.resolve()))
                        if not spec or not spec.loader:
                            continue
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        # Find decorated functions
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if getattr(attr, "is_tool", False):
                                name = getattr(attr, "tool_name")
                                desc = getattr(attr, "tool_description")
                                self.tools[name] = {
                                    "name": name,
                                    "description": f"{name} - {desc}",
                                    "func": attr
                                }
                                print(f"Loaded custom Skill Tool '{name}' from {py_file.name}")
                    except Exception as e:
                        print(f"Warning: Failed to load skill file {py_file.name}: {e}")

    def get_system_prompt_extension(self) -> str:
        """Inject tool definitions into the LLM system prompt."""
        if not self.tools:
            return ""
            
        tool_defs = []
        for t in self.tools.values():
            tool_defs.append(f"- {t['description']}")
            
        tools_str = "\n".join(tool_defs)
        
        return (
            "\n\n[SYSTEM INSTRUCTION: TOOL CALLING ENABLED]\n"
            "You have access to the following tools to answer the user request:\n"
            f"{tools_str}\n\n"
            "If you need to call a tool, generate exactly:\n"
            "<tool_call>{\"name\": \"tool_name\", \"arguments\": {\"arg_name\": \"value\"}}</tool_call>\n"
            "Do not output anything else. Stop generating immediately after the tool call.\n"
            "Once you receive the tool response, summarize the findings and respond to the user query normally."
        )

    async def execute_tool(self, call_json: str) -> str:
        """Execute a parsed tool call JSON string, with resilient fallback parsing."""
        try:
            # 1. Clean up string
            call_json = call_json.strip()
            
            # Remove potential markdown wrapping
            if call_json.startswith("```"):
                call_json = re.sub(r"^```[a-zA-Z0-9]*\n", "", call_json)
                call_json = re.sub(r"\n```$", "", call_json)
            call_json = call_json.strip()
            if not call_json:
                return "Error: Tool call content is empty."
                
            data = None

            
            # 2. Check if it looks like a function call instead of JSON
            if not call_json.startswith("{"):
                func_match = re.match(r"^(\w+)\((.*)\)$", call_json, re.DOTALL)
                if func_match:
                    name = func_match.group(1)
                    inner = func_match.group(2).strip()
                    args = {}
                    
                    # Parse arg=val patterns
                    kw_match = re.findall(r"(\w+)\s*=\s*['\"](.*?)['\"]", inner)
                    if kw_match:
                        args = {k: v for k, v in kw_match}
                    elif inner:
                        # Otherwise parse it as a single raw value passed to 'query'
                        val = re.sub(r"^['\"]|['\"]$", "", inner).strip()
                        args = {"query": val}
                        
                    data = {"name": name, "arguments": args}
            
            # 3. Try standard JSON parsing
            if not data:
                try:
                    data = json.loads(call_json)
                except json.JSONDecodeError as je:
                    # Try to fix single quotes to double quotes
                    if "'" in call_json and '"' not in call_json:
                        try:
                            data = json.loads(call_json.replace("'", '"'))
                        except Exception:
                            return f"Error: Invalid tool call syntax: {je}. Please try again using exactly: <tool_call>{{\"name\": \"tool_name\", \"arguments\": {{\"arg_name\": \"value\"}}}}</tool_call>"
                    else:
                        return f"Error: Invalid tool call syntax: {je}. Please try again using exactly: <tool_call>{{\"name\": \"tool_name\", \"arguments\": {{\"arg_name\": \"value\"}}}}</tool_call>"

            
            name = data.get("name")
            args = data.get("arguments", {})
            
            # 4. Resilient arguments resolution
            if not isinstance(args, dict):
                # If arguments is a raw value rather than a dict, map to query
                args = {"query": str(args)}
            elif not args:
                # If arguments is empty, treat all other top-level keys as parameters
                args = {k: v for k, v in data.items() if k != "name"}

            
            if name not in self.tools:
                return f"Error: Tool '{name}' is not registered."
                
            tool_entry = self.tools[name]
            func = tool_entry["func"]
            
            print(f"Executing tool '{name}' with args {args}...")
            if asyncio.iscoroutinefunction(func):
                result = await func(**args)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: func(**args))
                
            return str(result)
        except Exception as e:
            return f"Failed to execute tool: {e}"

    async def run_agent_loop(self, manager, target_model_id, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a ReAct/Agentic loop with the model, detecting and running tool calls
        before returning the final response.
        """
        backend = await manager.get_model(target_model_id)
        messages = payload.get("messages", [])
        
        # Inject system instructions with tools
        sys_extension = self.get_system_prompt_extension()
        
        # We clone payload and messages to prevent polluting chat history
        local_messages = list(messages)
        
        # Check if first message is system, else inject system message
        if local_messages and local_messages[0].get("role") == "system":
            system_msg = local_messages[0].copy()
            system_msg["content"] += sys_extension
            local_messages[0] = system_msg
        else:
            local_messages.insert(0, {
                "role": "system",
                "content": "You are a helpful assistant." + sys_extension
            })
            
        local_payload = dict(payload)
        local_payload["messages"] = local_messages
        local_payload["stream"] = False # Disable streaming for intermediate tool steps
        
        loop_limit = 5
        for step in range(loop_limit):
            # Run chat completion
            response = await backend.handle_chat_completion(local_payload)
            content = response["choices"][0]["message"]["content"]
            
            # Check for tool call tags
            match = re.search(r"<tool_call>(.*?)</tool_call>", content, re.DOTALL)
            if match:
                tool_call_json = match.group(1).strip()
                # Execute tool
                tool_result = await self.execute_tool(tool_call_json)
                
                # Append assistant tool invocation & tool result to history
                local_messages.append({"role": "assistant", "content": content})
                local_messages.append({
                    "role": "user",
                    "content": f"[TOOL RESPONSE]\n{tool_result}"
                })
                
                local_payload["messages"] = local_messages
                # Loop again to let model process tool output
                continue
            else:
                # No tool call, this is the final answer!
                return response
                
        # If we exceeded loops, return the last output
        return response
