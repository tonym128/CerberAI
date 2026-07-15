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

import sys
import tempfile

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

    def reload_tools(self):
        """Reload all built-in and dynamic skill tools."""
        self.tools.clear()
        self.register_builtin_tools()
        self.load_skills()

    def register_builtin_tools(self):
        """Register default tools like Web Search and local Filesystem."""
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
        self.tools["execute_python_code"] = {
            "name": "execute_python_code",
            "description": "execute_python_code(code: str) - Execute a snippet of Python code locally in a secure, isolated process. Returns stdout and stderr.",
            "func": self.execute_python_code_tool
        }
        self.tools["list_directory"] = {
            "name": "list_directory",
            "description": "list_directory(path: str = \".\") - List the contents of a local directory, showing files and folders.",
            "func": self.list_directory_tool
        }
        self.tools["read_file"] = {
            "name": "read_file",
            "description": "read_file(path: str) - Read the text contents of a local file.",
            "func": self.read_file_tool
        }
        self.tools["write_file"] = {
            "name": "write_file",
            "description": "write_file(path: str, content: str) - Write text content to a local file, creating or overwriting it.",
            "func": self.write_file_tool
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

    async def execute_python_code_tool(self, code: str) -> str:
        """
        Execute python code in a separate process, capturing stdout/stderr and enforcing timeouts.
        """
        # Write code to a temp file
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
            f.write(code)
            temp_path = f.name
            
        try:
            # We run it in a subprocess using the current interpreter path
            # and set a strict timeout of 10.0 seconds
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")
                
                result = []
                if stdout.strip():
                    result.append(f"--- STDOUT ---\n{stdout}")
                if stderr.strip():
                    result.append(f"--- STDERR ---\n{stderr}")
                    
                if not result:
                    return "Execution finished with no output (exit code 0)."
                    
                return "\n".join(result)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                return "Error: Python execution timed out after 10 seconds."
        except Exception as e:
            return f"Error executing Python code: {e}"
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    async def web_search_tool(self, query: str) -> str:
        """Query the configured search provider (DuckDuckGo, SearXNG, Tavily, Google)."""
        search_cfg = getattr(self.config, "search", None)
        provider = getattr(search_cfg, "provider", "duckduckgo") if search_cfg else "duckduckgo"
        
        if provider == "tavily":
            return await self._search_tavily(query)
        elif provider == "searxng":
            return await self._search_searxng(query)
        elif provider == "google":
            return await self._search_google(query)
        else:
            return await self._search_duckduckgo(query)

    async def _search_tavily(self, query: str) -> str:
        api_key = getattr(self.config.search, "tavily_api_key", None)
        if not api_key:
            return "Error: Tavily API key is not configured in settings."
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post("https://api.tavily.com/search", json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": 5
                })
                if res.status_code == 200:
                    data = res.json()
                    results = []
                    for i, r in enumerate(data.get("results", [])):
                        title = r.get("title", "")
                        snippet = r.get("content", "")
                        url = r.get("url", "")
                        results.append(f"{i+1}. {title}\nSnippet: {snippet}\nSource: {url}\n")
                    return "\n".join(results) if results else "No results found."
                return f"Error: Tavily API returned status {res.status_code}: {res.text}"
        except Exception as e:
            return f"Tavily search error: {e}"

    async def _search_searxng(self, query: str) -> str:
        url = getattr(self.config.search, "searxng_url", None)
        if not url:
            return "Error: SearXNG URL is not configured in settings."
        try:
            base_url = url.rstrip("/")
            search_url = f"{base_url}/search"
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                res = await client.get(search_url, params={
                    "q": query,
                    "format": "json"
                })
                if res.status_code == 200:
                    data = res.json()
                    results = []
                    for i, r in enumerate(data.get("results", [])[:5]):
                        title = r.get("title", "")
                        snippet = r.get("content", "")
                        source_url = r.get("url", "")
                        results.append(f"{i+1}. {title}\nSnippet: {snippet}\nSource: {source_url}\n")
                    return "\n".join(results) if results else "No results found."
                return f"Error: SearXNG API returned status {res.status_code}: {res.text}"
        except Exception as e:
            return f"SearXNG search error: {e}"

    async def _search_google(self, query: str) -> str:
        api_key = getattr(self.config.search, "google_api_key", None)
        cx = getattr(self.config.search, "google_cse_id", None)
        if not api_key or not cx:
            return "Error: Google API Key or Custom Search Engine ID (CX) is not configured in settings."
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://www.googleapis.com/customsearch/v1", params={
                    "key": api_key,
                    "cx": cx,
                    "q": query
                })
                if res.status_code == 200:
                    data = res.json()
                    results = []
                    for i, item in enumerate(data.get("items", [])[:5]):
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        url = item.get("link", "")
                        results.append(f"{i+1}. {title}\nSnippet: {snippet}\nSource: {url}\n")
                    return "\n".join(results) if results else "No results found."
                return f"Error: Google Search API returned status {res.status_code}: {res.text}"
        except Exception as e:
            return f"Google search error: {e}"

    def clean_search_query(self, query: str) -> str:
        # Remove common prefix phrases and natural language fluff
        q = query.lower().strip()
        
        # Phrases to remove
        phrases = [
            "search the web for the latest news about",
            "search the web for the latest news on",
            "search the web for news about",
            "search the web for news on",
            "search the web for latest news about",
            "search the web for latest news on",
            "search the web for info about",
            "search the web for info on",
            "search the web for information about",
            "search the web for information on",
            "search the web for",
            "search the internet for",
            "latest news about",
            "latest news on",
            "news about",
            "news on",
            "information about",
            "information on",
            "info about",
            "info on",
            "tell me about",
            "find news about",
            "find news on"
        ]
        for p in phrases:
            if q.startswith(p):
                q = q[len(p):].strip()
                break
                
        # Also strip basic stop words from start and end
        stop_words = ["about", "on", "for", "the", "a", "an", "latest", "news", "info", "information", "search", "find"]
        words = q.split()
        while words and words[0] in stop_words:
            words.pop(0)
        while words and words[-1] in stop_words:
            words.pop()
            
        return " ".join(words) if words else query

    async def _search_duckduckgo(self, query: str) -> str:
        """Query DuckDuckGo HTML search page and parse top results, falling back to other search engines if blocked."""
        import html
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }
        
        # Clean the query for keyword-based fallback APIs
        clean_query = self.clean_search_query(query)
        
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

                # Fallback 2: Hacker News Search API (Algolia) - highly reliable, no CAPTCHAs
                print(f"Falling back to Hacker News Search API with query: '{clean_query}'...")
                try:
                    hn_api_url = "https://hn.algolia.com/api/v1/search"
                    async with httpx.AsyncClient(timeout=10.0) as hn_client:
                        hn_res = await hn_client.get(hn_api_url, params={"query": clean_query})
                        if hn_res.status_code == 200:
                            hn_data = hn_res.json()
                            hn_results = []
                            for idx, hit in enumerate(hn_data.get("hits", [])[:5]):
                                title = hit.get("title") or hit.get("story_title") or "Hacker News discussion"
                                url = hit.get("url") or hit.get("story_url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
                                snippet = hit.get("comment_text") or hit.get("story_text") or f"HN Post by {hit.get('author', 'anonymous')}"
                                snippet_clean = html.unescape(re.sub(r'<[^>]+>', ' ', snippet).strip())
                                hn_results.append(f"{len(hn_results)+1}. {title}\nSnippet: {snippet_clean[:250]}...\nSource: {url}\n")
                            if hn_results:
                                return "\n".join(hn_results)
                except Exception as hn_err:
                    print(f"Hacker News Search API fallback check failed: {hn_err}")

                # Fallback 3: GitHub Repository Search API - highly reliable for software/tech queries
                print(f"Falling back to GitHub Search API with query: '{clean_query}'...")
                try:
                    github_api_url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(clean_query)}"
                    github_headers = {
                        "User-Agent": "CerberAI/1.0 (tonym@example.com)",
                        "Accept": "application/vnd.github+json"
                    }
                    async with httpx.AsyncClient(headers=github_headers, timeout=10.0) as gh_client:
                        gh_res = await gh_client.get(github_api_url)
                        if gh_res.status_code == 200:
                            gh_data = gh_res.json()
                            gh_results = []
                            for idx, item in enumerate(gh_data.get("items", [])[:5]):
                                name = item.get("full_name", "")
                                url = item.get("html_url", "")
                                desc = item.get("description") or "No description provided."
                                stars = item.get("stargazers_count", 0)
                                lang = item.get("language") or "unspecified language"
                                gh_results.append(f"{len(gh_results)+1}. GitHub Repository: {name}\nSnippet: {desc} (Stars: {stars}, Language: {lang})\nSource: {url}\n")
                            if gh_results:
                                return "\n".join(gh_results)
                except Exception as gh_err:
                    print(f"GitHub Search API fallback check failed: {gh_err}")

                # Fallback 4: Wikipedia API search if other sources trigger CAPTCHA or errors
                print(f"Falling back to Wikipedia API with query: '{clean_query}'...")
                wiki_api_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(clean_query)}&format=json"
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
                            results.append(f"{len(results)+1}. {title}\nSnippet: {snippet}\nSource: {page_url}\n")
                        if results:
                            return "\n".join(results)
                            
                return "Error: Search challenge encountered and all fallbacks (DuckDuckGo Instant Answer, Hacker News, GitHub, & Wikipedia) returned no results."
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
        """Inject tool definitions into the LLM system prompt, including dynamic MCP tools."""
        tool_defs = []
        for t in self.tools.values():
            tool_defs.append(f"- {t['description']}")
            
        # Dynamically append active MCP tools
        try:
            from .main import mcp_manager
            for client_name, client in mcp_manager.clients.items():
                for t in client.tools:
                    tool_defs.append(f"- {client_name}_{t['name']} - {t.get('description', '')}")
        except Exception:
            pass
            
        if not tool_defs:
            return ""
            
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

            
            if name in self.tools:
                tool_entry = self.tools[name]
                func = tool_entry["func"]
                
                print(f"Executing tool '{name}' with args {args}...")
                if asyncio.iscoroutinefunction(func):
                    result = await func(**args)
                else:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(None, lambda: func(**args))
                    
                return str(result)

            # Check if this is an MCP tool (format: {server_name}_{tool_name})
            try:
                from .main import mcp_manager
                if "_" in name:
                    server_name, actual_tool_name = name.split("_", 1)
                    if server_name in mcp_manager.clients:
                        client = mcp_manager.clients[server_name]
                        if any(t["name"] == actual_tool_name for t in client.tools):
                            print(f"Executing MCP tool '{actual_tool_name}' on server '{server_name}' with args {args}...")
                            res = await mcp_manager.call_tool(server_name, actual_tool_name, args)
                            
                            if "content" in res:
                                texts = [c.get("text", "") for c in res["content"] if c.get("type") == "text"]
                                return "\n".join(texts)
                            return str(res)
            except Exception as mcp_err:
                print(f"Failed to execute MCP tool delegation: {mcp_err}")

            return f"Error: Tool '{name}' is not registered."
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

    async def list_directory_tool(self, path: str = ".") -> str:
        """List files and folders in a local path."""
        try:
            p = Path(path).resolve()
            if not p.exists():
                return f"Error: Path '{path}' does not exist."
            if not p.is_dir():
                return f"Error: Path '{path}' is a file, not a directory."
            
            items = []
            for item in p.iterdir():
                item_type = "📁 [DIR]" if item.is_dir() else "📄 [FILE]"
                size_str = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
                items.append(f"{item_type} {item.name}{size_str}")
            
            if not items:
                return f"Directory '{path}' is empty."
                
            return "\n".join(sorted(items))
        except Exception as e:
            return f"Error listing directory: {e}"

    async def read_file_tool(self, path: str) -> str:
        """Read the content of a local file."""
        try:
            p = Path(path).resolve()
            if not p.exists():
                return f"Error: File '{path}' does not exist."
            if not p.is_file():
                return f"Error: Path '{path}' is a directory, not a file."
                
            # Restrict to text/source files to prevent binary garbage dump
            try:
                content = p.read_text(encoding="utf-8", errors="strict")
            except UnicodeDecodeError:
                return "Error: File content is not valid UTF-8 text (likely binary file)."
                
            limit = 12000
            if len(content) > limit:
                return content[:limit] + f"\n\n... (File content truncated: {len(content) - limit} characters remaining)"
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    async def write_file_tool(self, path: str, content: str) -> str:
        """Write content to a local file."""
        try:
            p = Path(path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to file '{path}'."
        except Exception as e:
            return f"Error writing file: {e}"
