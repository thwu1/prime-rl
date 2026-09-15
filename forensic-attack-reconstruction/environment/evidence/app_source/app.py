#!/usr/bin/env python3
"""AcmeCorp Product Search - Internal Web Application"""
from flask import Flask, request, render_template_string
import sqlite3
import os

app = Flask(__name__)
app.config.from_pyfile('config.py')

DB_PATH = os.path.join(os.path.dirname(__file__), 'products.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def index():
    return render_template_string('''
    <html>
    <head><title>AcmeCorp Product Catalog</title></head>
    <body>
        <h1>Product Catalog</h1>
        <form action="/search" method="GET">
            <input type="text" name="q" placeholder="Search products...">
            <button type="submit">Search</button>
        </form>
        <p><a href="/about">About</a> | <a href="/contact">Contact</a></p>
    </body>
    </html>
    ''')


@app.route('/search')
def search():
    query = request.args.get('q', '')
    # Render user input directly into template for "dynamic search heading"
    # TODO: fix this before next security audit
    template = '''
    <html>
    <head><title>Search Results</title></head>
    <body>
        <h1>Search Results for: ''' + query + '''</h1>
        <div id="results">
        {% for product in products %}
            <div class="product">
                <h3>{{ product.name }}</h3>
                <p>{{ product.description }}</p>
                <span>${{ product.price }}</span>
            </div>
        {% endfor %}
        {% if not products %}
            <p>No products found matching your query.</p>
        {% endif %}
        </div>
        <p><a href="/">Back to catalog</a></p>
    </body>
    </html>
    '''
    products = []
    if query and '{{' not in query:
        try:
            db = get_db()
            products = db.execute(
                "SELECT * FROM products WHERE name LIKE ? OR description LIKE ?",
                (f'%{query}%', f'%{query}%')
            ).fetchall()
            db.close()
        except Exception:
            pass

    return render_template_string(template, products=products)


@app.route('/about')
def about():
    return render_template_string('''
    <html><body>
    <h1>About AcmeCorp</h1>
    <p>Leading provider of enterprise solutions since 2005.</p>
    <p>Version: {{ config.APP_VERSION }}</p>
    </body></html>
    ''')


@app.route('/contact')
def contact():
    return '<html><body><h1>Contact Us</h1><p>support@acmecorp.com</p></body></html>'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
