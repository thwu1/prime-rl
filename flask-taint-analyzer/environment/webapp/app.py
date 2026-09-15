"""
Flask web application with various security patterns.
Some routes contain vulnerabilities, others are properly secured.
"""
from flask import Flask, request, render_template_string
import os
import sqlite3
import subprocess
import requests as req_lib

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect("/tmp/app.db")
    return conn


def build_user_query(table_name, filter_clause):
    """Helper that constructs a SQL query string from arguments."""
    return f"SELECT * FROM {table_name} WHERE {filter_clause}"


class FileManager:
    def __init__(self, base):
        self.base = base

    def get_content(self, name):
        target = os.path.normpath(os.path.join(self.base, name))
        with open(target) as f:
            return f.read()


file_mgr = FileManager("/var/data")


@app.route("/search")
def search():
    q = request.args.get("q", "")
    db = get_db()
    results = db.execute(
        "SELECT * FROM products WHERE name LIKE '%" + q + "%'"
    ).fetchall()
    return str(results)


@app.route("/search_safe")
def search_safe():
    q = request.args.get("q", "")
    db = get_db()
    results = db.execute(
        "SELECT * FROM products WHERE name LIKE ?", ("%" + q + "%",)
    ).fetchall()
    return str(results)


@app.route("/ping")
def ping():
    host = request.args.get("host", "")
    output = os.popen("ping -c 1 " + host).read()
    return output


@app.route("/ping_safe")
def ping_safe():
    host = request.args.get("host", "")
    result = subprocess.run(
        ["ping", "-c", "1", host], capture_output=True, text=True
    )
    return result.stdout


@app.route("/read_file")
def read_file():
    filename = request.args.get("file", "")
    with open("/var/data/" + filename) as f:
        return f.read()


@app.route("/read_file_safe")
def read_file_safe():
    filename = request.args.get("file", "")
    base = "/var/data"
    full = os.path.realpath(os.path.join(base, filename))
    if not full.startswith(base):
        return "Access denied", 403
    with open(full) as f:
        return f.read()


@app.route("/greet")
def greet():
    name = request.args.get("name", "")
    return render_template_string("<h1>Hello " + name + "</h1>")


@app.route("/fetch")
def fetch_url():
    url = request.args.get("url", "")
    resp = req_lib.get(url)
    return resp.text


@app.route("/users")
def users():
    role = request.args.get("role", "")
    query = build_user_query("users", "role = '" + role + "'")
    db = get_db()
    return str(db.execute(query).fetchall())


@app.route("/convert")
def convert():
    fmt = request.args.get("format", "png")
    cmd = f"convert /tmp/input.pdf -format {fmt} /tmp/output.{fmt}"
    subprocess.call(cmd, shell=True)
    return "Converted"


@app.route("/lookup")
def lookup():
    domain = request.args.get("domain", "")
    if not all(c.isalnum() or c == "." for c in domain):
        return "Invalid domain", 400
    output = os.popen("nslookup " + domain).read()
    return output


@app.route("/doc")
def doc():
    name = request.args.get("name", "")
    return file_mgr.get_content(name)
