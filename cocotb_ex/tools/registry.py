import os
import subprocess
import sys
import shlex

class ToolRegistry:
    """
    Registry for internal python tools to decouple script invocation from the pipeline logic.
    Ensures tools are invoked consistently and their paths are managed in one place.
    """
    def __init__(self, workspace_root):
        self.workspace_root = os.path.abspath(workspace_root)
        # Assuming tools are always in 'tools/' relative to workspace root
        self.tools_dir = os.path.join(self.workspace_root, "tools")

    def get_tool_path(self, tool_name):
        """Resolve tool name to absolute path."""
        # Handle both "tool_name" and "tool_name.py"
        if not tool_name.endswith(".py"):
            tool_name += ".py"
        
        path = os.path.join(self.tools_dir, tool_name)
        if not os.path.exists(path):
            return None
        return path

    def is_available(self, tool_name):
        return self.get_tool_path(tool_name) is not None

    def run_tool(self, tool_name, args, capture_output=True, timeout=None, check=False, cwd=None):
        """
        Run a python tool from the tools directory.
        
        Args:
            tool_name: Name of the tool script (e.g. 'extract_log_excerpt')
            args: List of string arguments
            capture_output: Whether to capture stdout/stderr
            timeout: Timeout in seconds
            check: Raise CalledProcessError on non-zero exit
            cwd: Working directory (defaults to workspace root)
            
        Returns:
            subprocess.CompletedProcess
        """
        tool_path = self.get_tool_path(tool_name)
        if not tool_path:
            raise FileNotFoundError(f"Tool '{tool_name}' not found in {self.tools_dir}")

        cmd = [sys.executable, tool_path] + [str(a) for a in args]
        
        # Default CWD to workspace root if not specified, 
        # so tools running relative paths work as expected.
        working_dir = cwd or self.workspace_root

        # print(f"[DEBUG] Invoking tool: {tool_name} with args: {args}")
        
        try:
            return subprocess.run(
                cmd,
                capture_output=capture_output,
                text=True,
                timeout=timeout,
                check=check,
                cwd=working_dir
            )
        except subprocess.TimeoutExpired as e:
            print(f"[WARN] Tool {tool_name} timed out after {timeout}s")
            raise e
