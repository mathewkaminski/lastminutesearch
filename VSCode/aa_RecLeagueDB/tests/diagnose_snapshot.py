"""Diagnostic script to inspect what browser_snapshot actually returns from Playwright MCP."""

import asyncio
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def diagnose():
    server_params = StdioServerParameters(
        command="npx",
        args=["@playwright/mcp@latest", "--headless"],
    )

    print("Connecting to Playwright MCP server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected.\n")

            # Step 1: Navigate to the URL
            target_url = "https://www.ottawavolleysixes.com/home/volleyball"
            print(f"Calling browser_navigate({target_url!r})...")
            nav_result = await session.call_tool("browser_navigate", arguments={"url": target_url})

            print(f"  nav_result type: {type(nav_result)}")
            print(f"  nav_result.content count: {len(nav_result.content)}")
            for i, item in enumerate(nav_result.content):
                print(f"  [navigate item {i}] type={type(item).__name__!r}, .type attr={getattr(item, 'type', 'N/A')!r}")
                if hasattr(item, "text"):
                    print(f"    .text (first 200): {item.text[:200]!r}")
                if hasattr(item, "resource"):
                    res = item.resource
                    print(f"    .resource type: {type(res).__name__!r}")
                    if hasattr(res, "text"):
                        print(f"    .resource.text (first 200): {res.text[:200]!r}")
                    if hasattr(res, "uri"):
                        print(f"    .resource.uri: {res.uri!r}")
            print()

            # Step 2: Call browser_snapshot
            print("Calling browser_snapshot()...")
            snap_result = await session.call_tool("browser_snapshot", arguments={})

            print(f"  snap_result type: {type(snap_result)}")
            print(f"  snap_result.isError: {snap_result.isError}")
            print(f"  snap_result.content count: {len(snap_result.content)}")
            print()

            total_text_from_text_attr = 0
            total_text_from_resource = 0

            for i, item in enumerate(snap_result.content):
                item_type_name = type(item).__name__
                mcp_type_attr = getattr(item, "type", "N/A")
                print(f"--- Content item [{i}] ---")
                print(f"  Python type: {item_type_name!r}")
                print(f"  .type attr:  {mcp_type_attr!r}")
                print(f"  All attributes: {[a for a in dir(item) if not a.startswith('_')]}")

                # Check .text attribute (TextContent path)
                if hasattr(item, "text"):
                    text_val = item.text
                    total_text_from_text_attr += len(text_val)
                    print(f"  .text length: {len(text_val)} chars")
                    print(f"  .text first 500 chars:\n    {text_val[:500]!r}")
                else:
                    print("  .text: NOT PRESENT")

                # Check .resource attribute (EmbeddedResource path)
                if hasattr(item, "resource"):
                    res = item.resource
                    res_type = type(res).__name__
                    print(f"  .resource type: {res_type!r}")
                    print(f"  .resource attributes: {[a for a in dir(res) if not a.startswith('_')]}")
                    if hasattr(res, "uri"):
                        print(f"  .resource.uri: {res.uri!r}")
                    if hasattr(res, "mimeType"):
                        print(f"  .resource.mimeType: {res.mimeType!r}")
                    if hasattr(res, "text"):
                        total_text_from_resource += len(res.text)
                        print(f"  .resource.text length: {len(res.text)} chars")
                        print(f"  .resource.text first 500 chars:\n    {res.text[:500]!r}")
                    if hasattr(res, "blob"):
                        print(f"  .resource.blob length: {len(res.blob)} chars (base64)")

                # Check .data attribute (ImageContent path)
                if hasattr(item, "data"):
                    print(f"  .data (image/binary) length: {len(item.data)} chars")
                    if hasattr(item, "mimeType"):
                        print(f"  .mimeType: {item.mimeType!r}")

                # Check .url attribute (ResourceLink path)
                if hasattr(item, "url") and not hasattr(item, "text"):
                    print(f"  .url: {item.url!r}")

                print()

            print("=" * 60)
            print("SUMMARY")
            print("=" * 60)
            print(f"Total chars captured via item.text:          {total_text_from_text_attr}")
            print(f"Total chars captured via item.resource.text: {total_text_from_resource}")
            print()

            # Reproduce the exact bug
            result_text_current = "\n".join(
                item.text
                for item in snap_result.content
                if hasattr(item, "text")
            )
            print(f"Current mcp_navigator.py captures:           {len(result_text_current)} chars")
            print(f"Current capture preview: {result_text_current[:300]!r}")
            print()

            # Proposed fix: also extract from EmbeddedResource
            result_text_fixed_parts = []
            for item in snap_result.content:
                if hasattr(item, "text"):
                    result_text_fixed_parts.append(item.text)
                elif hasattr(item, "resource") and hasattr(item.resource, "text"):
                    result_text_fixed_parts.append(item.resource.text)
            result_text_fixed = "\n".join(result_text_fixed_parts)
            print(f"Fixed extraction would capture:               {len(result_text_fixed)} chars")
            print(f"Fixed capture preview: {result_text_fixed[:300]!r}")


if __name__ == "__main__":
    asyncio.run(diagnose())
