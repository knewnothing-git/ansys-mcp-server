#!/usr/bin/env python3
"""
Ansys MCP Server
A Model Context Protocol server for interfacing with Ansys simulation software.
"""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Union
import json
from pathlib import Path

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.types as types

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ansys-mcp")

class AnsysInterface:
    """Interface for Ansys operations"""
    
    def __init__(self):
        self.ansys_path = os.environ.get('ANSYS_ROOT', '')
        self.working_directory = Path.cwd() / "ansys_work"
        self.working_directory.mkdir(exist_ok=True)
        self.mapdl_session = None
        
    def check_ansys_installation(self) -> Dict[str, Any]:
        """Check if Ansys is installed and accessible"""
        try:
            # Try to import PyAnsys libraries
            available_modules = {}
            
            try:
                import ansys.fluent.core as pyfluent
                available_modules['fluent'] = True
            except ImportError:
                available_modules['fluent'] = False
                
            try:
                import ansys.mapdl.core as pymapdl
                available_modules['mapdl'] = True
            except ImportError:
                available_modules['mapdl'] = False
                
            try:
                import ansys.geometry.core as pyansys_geometry
                available_modules['geometry'] = True
            except ImportError:
                available_modules['geometry'] = False
                
            return {
                "status": "available" if any(available_modules.values()) else "not_found",
                "modules": available_modules,
                "ansys_path": self.ansys_path,
                "working_directory": str(self.working_directory)
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def create_fluent_session(self, precision: str = "double", 
                                  dimension: str = "3d") -> Dict[str, Any]:
        """Create a new Fluent session"""
        try:
            import ansys.fluent.core as pyfluent
            
            session = pyfluent.launch_fluent(
                precision=precision,
                dimension=dimension,
                mode="solver"
            )
            
            return {
                "status": "success",
                "session_id": id(session),
                "precision": precision,
                "dimension": dimension
            }
        except ImportError:
            return {"status": "error", "message": "PyFluent not available"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def create_mapdl_session(self, run_location: Optional[str] = None) -> Dict[str, Any]:
        """Create a new MAPDL session, replacing any existing one"""
        try:
            import ansys.mapdl.core as pymapdl

            if self.mapdl_session is not None:
                try:
                    self.mapdl_session.exit()
                except Exception:
                    pass

            mapdl = pymapdl.launch_mapdl(
                run_location=run_location or str(self.working_directory)
            )
            self.mapdl_session = mapdl

            return {
                "status": "success",
                "session_id": id(mapdl),
                "version": mapdl.version,
                "run_location": mapdl.directory
            }
        except ImportError:
            return {"status": "error", "message": "PyMAPDL not available"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def read_ansys_file(self, file_path: str) -> Dict[str, Any]:
        """Read various Ansys file formats"""
        try:
            path = Path(file_path)
            if not path.exists():
                return {"status": "error", "message": f"File not found: {file_path}"}
            
            file_info = {
                "path": str(path),
                "size": path.stat().st_size,
                "extension": path.suffix.lower()
            }
            
            # Handle different file types
            if path.suffix.lower() in ['.cas', '.dat']:
                file_info["type"] = "Fluent case/data file"
            elif path.suffix.lower() in ['.inp', '.cdb']:
                file_info["type"] = "MAPDL input/database file"
            elif path.suffix.lower() in ['.rst', '.rth']:
                file_info["type"] = "MAPDL result file"
            else:
                file_info["type"] = "Unknown Ansys file"
            
            # For text-based files, read content preview
            if path.suffix.lower() in ['.inp', '.jou']:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content_preview = f.read(1000)  # First 1000 chars
                file_info["preview"] = content_preview
            
            return {"status": "success", "file_info": file_info}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    async def run_mapdl_commands(self, commands: List[str]) -> Dict[str, Any]:
        """Execute MAPDL commands against the active session, launching one if needed"""
        try:
            import ansys.mapdl.core as pymapdl

            if self.mapdl_session is None:
                launch_result = await self.create_mapdl_session()
                if launch_result["status"] != "success":
                    return launch_result

            results = []
            for cmd in commands:
                try:
                    output = self.mapdl_session.run(cmd)
                    results.append({
                        "command": cmd,
                        "status": "executed",
                        "output": output
                    })
                except Exception as cmd_error:
                    results.append({
                        "command": cmd,
                        "status": "error",
                        "output": str(cmd_error)
                    })

            return {
                "status": "success",
                "commands_executed": len(commands),
                "results": results
            }

        except ImportError:
            return {"status": "error", "message": "PyMAPDL not available"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Initialize Ansys interface
ansys_interface = AnsysInterface()

# Create the MCP server
server = Server("ansys-mcp")

@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    """List available Ansys resources"""
    return [
        Resource(
            uri="ansys://status",
            name="Ansys Installation Status",
            description="Check Ansys installation and available modules",
            mimeType="application/json",
        ),
        Resource(
            uri="ansys://working-directory",
            name="Working Directory",
            description="Current Ansys working directory and files",
            mimeType="application/json",
        ),
    ]

@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    """Read Ansys resources"""
    if uri == "ansys://status":
        status = ansys_interface.check_ansys_installation()
        return json.dumps(status, indent=2)
    
    elif uri == "ansys://working-directory":
        work_dir = ansys_interface.working_directory
        files = []
        if work_dir.exists():
            for file in work_dir.iterdir():
                if file.is_file():
                    files.append({
                        "name": file.name,
                        "size": file.stat().st_size,
                        "modified": file.stat().st_mtime
                    })
        
        return json.dumps({
            "directory": str(work_dir),
            "files": files
        }, indent=2)
    
    else:
        raise ValueError(f"Unknown resource: {uri}")

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available Ansys tools"""
    return [
        Tool(
            name="check_ansys_status",
            description="Check Ansys installation status and available modules",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="create_fluent_session",
            description="Create a new Ansys Fluent session",
            inputSchema={
                "type": "object",
                "properties": {
                    "precision": {
                        "type": "string",
                        "enum": ["single", "double"],
                        "default": "double",
                        "description": "Precision for calculations"
                    },
                    "dimension": {
                        "type": "string",
                        "enum": ["2d", "3d"],
                        "default": "3d",
                        "description": "Simulation dimension"
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="create_mapdl_session",
            description="Create a new Ansys MAPDL session",
            inputSchema={
                "type": "object",
                "properties": {
                    "run_location": {
                        "type": "string",
                        "description": "Directory to run MAPDL (optional)"
                    }
                },
                "required": [],
            },
        ),
        Tool(
            name="read_ansys_file",
            description="Read and analyze Ansys files (.cas, .dat, .inp, .rst, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the Ansys file"
                    }
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="run_mapdl_commands",
            description="Execute MAPDL commands against the active session (auto-launches one if none exists)",
            inputSchema={
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of MAPDL commands to execute"
                    }
                },
                "required": ["commands"],
            },
        ),
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Handle tool calls"""
    if arguments is None:
        arguments = {}
    
    try:
        if name == "check_ansys_status":
            result = ansys_interface.check_ansys_installation()
            
        elif name == "create_fluent_session":
            result = await ansys_interface.create_fluent_session(
                precision=arguments.get("precision", "double"),
                dimension=arguments.get("dimension", "3d")
            )
            
        elif name == "create_mapdl_session":
            result = await ansys_interface.create_mapdl_session(
                run_location=arguments.get("run_location")
            )
            
        elif name == "read_ansys_file":
            result = await ansys_interface.read_ansys_file(
                file_path=arguments["file_path"]
            )
            
        elif name == "run_mapdl_commands":
            result = await ansys_interface.run_mapdl_commands(
                commands=arguments["commands"]
            )
            
        else:
            raise ValueError(f"Unknown tool: {name}")
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        logger.error(f"Error in tool {name}: {e}")
        error_result = {"status": "error", "message": str(e)}
        return [types.TextContent(type="text", text=json.dumps(error_result, indent=2))]

async def main():
    """Main entry point"""
    # Import here to avoid issues if mcp package isn't available
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="ansys-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())