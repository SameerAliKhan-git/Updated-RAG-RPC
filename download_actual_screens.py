import os
import urllib.request
import urllib.error

screens = {
    "shader.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1NmMwNjQyNjRmZjcwMzM4NWNiMGI1MzJjYmI0EgsSBxCAofnS9h0YAZIBIwoKcHJvamVjdF9pZBIVQhM4OTEwMjg4MDE3OTE3NzY4NTI2&filename=&opi=89354086",
    "ask_new_thread.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1NmMwNjkxOWIxZDgwMzM4NWNiMGI1MzJjYmI0EgsSBxCAofnS9h0YAZIBIwoKcHJvamVjdF9pZBIVQhM4OTEwMjg4MDE3OTE3NzY4NTI2&filename=&opi=89354086",
    "agent_reasoning.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1NmMwNmFhODQ1NDEwNTQ5ZDNiYjhlMzdhMGIzEgsSBxCAofnS9h0YAZIBIwoKcHJvamVjdF9pZBIVQhM4OTEwMjg4MDE3OTE3NzY4NTI2&filename=&opi=89354086",
    "library.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1NmMwNmFjZGQzYzIwMmE5YWU5MTUyMDQ4ZTYzEgsSBxCAofnS9h0YAZIBIwoKcHJvamVjdF9pZBIVQhM4OTEwMjg4MDE3OTE3NzY4NTI2&filename=&opi=89354086",
    "knowledge_flow.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1NmMwZGUxYzliYmMwN2M0ZDhlYWE1MDg3MTI0EgsSBxCAofnS9h0YAZIBIwoKcHJvamVjdF9pZBIVQhM4OTEwMjg4MDE3OTE3NzY4NTI2&filename=&opi=89354086",
    "mobile_ask.html": "https://contribution.usercontent.google.com/download?c=CgthaWRhX2NvZGVmeBJ7Eh1hcHBfY29tcGFuaW9uX2dlbmVyYXRlZF9maWxlcxpaCiVodG1sXzAwMDY1NmMwNmEyZjMwN2QwMWE2MzFkMWMwM2I1NTQ2EgsSBxCAofnS9h0YAZIBIwoKcHJvamVjdF9pZBIVQhM4OTEwMjg4MDE3OTE3NzY4NTI2&filename=&opi=89354086"
}

out_dir = "stitch_assets_actual"
os.makedirs(out_dir, exist_ok=True)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
}

for name, url in screens.items():
    print(f"Downloading {name}...")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            content = response.read()
            with open(os.path.join(out_dir, name), "wb") as f:
                f.write(content)
        print(f"Successfully downloaded {name}")
    except Exception as e:
        print(f"Failed to download {name}: {e}")
