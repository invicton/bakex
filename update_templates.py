import os

for path in [
    "/Data/Vamsh_Projects/Stratum/stratum/api/ui.py",
    "/Data/Vamsh_Projects/Stratum/stratum/api/blueprints.py",
]:
    if not os.path.exists(path):
        continue
    with open(path) as f:
        lines = f.readlines()

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "return templates.TemplateResponse(" in line:
            new_lines.append(line)
            # Next line is the template name
            i += 1
            name_line = lines[i]
            # Replace `"template_name.html",` with `request=request, name="template_name.html",`
            # Or just replace the string part
            # It usually looks like: `        "index.html",` or `        template_name,`
            name_content = name_line.strip()
            if name_content.endswith(","):
                name_content = name_content[:-1]

            # Count leading spaces
            spaces = len(name_line) - len(name_line.lstrip())
            indent = " " * spaces

            new_lines.append(f"{indent}request=request, name={name_content}, context=\n")
        else:
            new_lines.append(line)
        i += 1

    with open(path, "w") as f:
        f.writelines(new_lines)
    print(f"Updated {path}")
