import os


EXTENSIONS = [".py", ".c"]
BLACKLIST = [
    "build",
    "start_client.py",
    "start_server.py",
    "start_gui.py",
    "setup.py",
    "make_tree.py",
]


def make_tree(dir):
    for i in os.listdir(dir):
        p = os.path.join(dir, i)
        if os.path.isdir(p):
            if i in BLACKLIST:
                continue
            make_tree(p)
            continue
        if i in BLACKLIST:
            continue

        for j in EXTENSIONS:
            if i.endswith(j):
                break
        else:
            continue

        inc = dir[2:].replace(os.path.sep, ".")
        inc += "." + i.split(".")[0]
        inc = inc.replace("_", "\\_")

        with open(p) as f:
            content = f.read()
        if not content:
            continue

        content = content.replace("\r", "").split("\n")
        for n, i in enumerate(content):
            in_string = []
            in_comment = False
    
            new = ""
            for j in i:
                if not in_comment:
                    if j == "'":
                        new += j
                        if '"' in in_string:
                            pass
                        elif "'" in in_string:
                            in_string.remove("'")
                        else:
                            in_string.append("'")
                        continue
                    elif j == '"':
                        new += j
                        if "'" in in_string:
                            pass
                        elif '"' in in_string:
                            in_string.remove('"')
                        else:
                            in_string.append('"')
                        continue

                if not in_string and j == "#":
                    in_comment = True

                if in_comment and j == "_":
                    new += "\\_"
                else:
                    if new == "#define ":
                        new = "\\##define "
                    new += j

            content[n] = new
        content = "\n".join(content)

        type = "ccode" if i.endswith(".c") else "pythoncode"

        with open("out.tex", "a") as f:
            f.write(f"\\subsection{{{inc}}}\n")
            f.write(f"\\begin{{{type}}}\n{content}\\end{{{type}}}\n")


make_tree(".")
