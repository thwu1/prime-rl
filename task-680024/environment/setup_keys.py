import json
import os

data = json.load(open("/tmp/keys.json"))
os.makedirs("/app/keys", exist_ok=True)
for k in data["keys"]:
    path = "/app/keys/{}.json".format(k["id"])
    with open(path, "w") as f:
        json.dump({"id": k["id"], "n_hex": k["n_hex"], "e": k["e"]}, f, indent=2)
