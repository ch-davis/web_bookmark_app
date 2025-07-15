import os
import sys 
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
import sqlite3
import requests
from urllib.parse import urlparse
from PIL import Image
import io

# --- 路径配置：适应打包后的环境 (PyInstaller) ---
if getattr(sys, 'frozen', False):
    template_folder_path = os.path.join(sys._MEIPASS, 'templates')
    static_folder_path = os.path.join(sys._MEIPASS, 'static')
    app = Flask(__name__, template_folder=template_folder_path, static_folder=static_folder_path)

    APP_ROOT = os.path.abspath(os.path.dirname(sys.argv[0]))
    DATABASE = os.path.join(APP_ROOT, 'bookmarks.db')
    FAVICON_CACHE_DIR = os.path.join(APP_ROOT, 'favicon_cache')
else:
    app = Flask(__name__)
    DATABASE = 'bookmarks.db'
    FAVICON_CACHE_DIR = 'favicon_cache'

# 确保 Favicon 缓存目录存在
if not os.path.exists(FAVICON_CACHE_DIR):
    try:
        os.makedirs(FAVICON_CACHE_DIR)
        print(f"Created favicon cache directory: {FAVICON_CACHE_DIR}")
    except OSError as e:
        print(f"Error creating favicon cache directory {FAVICON_CACHE_DIR}: {e}")

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        conn = get_db_connection()
        
        # 步骤 1: 确保 bookmarks 表存在 (如果不存在就创建它)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                favicon_path TEXT DEFAULT NULL,
                fa_icon_class TEXT DEFAULT NULL 
            );
        ''')
        conn.commit() # 提交创建表的改动

        # 步骤 2: 检查 fa_icon_class 列是否存在，如果不存在则添加
        # 这一步只有在表已经存在的情况下才能安全执行
        try:
            cursor = conn.execute("PRAGMA table_info(bookmarks)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if 'fa_icon_class' not in columns:
                conn.execute('ALTER TABLE bookmarks ADD COLUMN fa_icon_class TEXT DEFAULT NULL')
                conn.commit()
                print("Added 'fa_icon_class' column to bookmarks table.")
            else:
                print("Table 'bookmarks' and column 'fa_icon_class' are already up to date.")
        except sqlite3.OperationalError as e:
            # 如果在 PRAGMA table_info 之前，表就因为某些原因不存在
            # (尽管 CREATE TABLE IF NOT EXISTS 应该处理了这种情况)
            print(f"Error checking table info (this might happen if DB is just created): {e}")
        except Exception as e:
            print(f"An unexpected error occurred during DB schema check: {e}")

        conn.close()

# 在应用启动时初始化数据库
init_db()

def fetch_and_cache_favicon(bookmark_id, url):
    parsed_url = urlparse(url)
    favicon_url_candidates = [
        f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico",
    ]
    
    print(f"Attempting to fetch favicon for: {url}")

    for favicon_url in favicon_url_candidates:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(favicon_url, headers=headers, timeout=5, stream=True)
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '').lower()
            print(f"Fetched {favicon_url}, Content-Type: {content_type}")

            img_data = io.BytesIO(response.content)
            
            try:
                img = Image.open(img_data)
                ext = '.png'
                local_filename = f"favicon_{bookmark_id}{ext}"
                local_filepath = os.path.join(FAVICON_CACHE_DIR, local_filename)
                
                img.save(local_filepath, format="PNG") 
                
                print(f"Favicon for {url} saved to {local_filepath}")
                return f"/favicons/{local_filename}"
            except IOError:
                print(f"Could not open image data from {favicon_url} with Pillow. Content-Type: {content_type}. Attempting direct save.")
                if content_type.startswith('image/'):
                    ext_map = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/x-icon': '.ico', 'image/svg+xml': '.svg'}
                    ext = ext_map.get(content_type, '.bin')
                    local_filename = f"favicon_{bookmark_id}{ext}"
                    local_filepath = os.path.join(FAVICON_CACHE_DIR, local_filename)
                    with open(local_filepath, 'wb') as f:
                        f.write(response.content)
                    print(f"Favicon for {url} directly saved to {local_filepath}")
                    return f"/favicons/{local_filename}"
                else:
                    print(f"Content-Type {content_type} is not a recognized image type for direct save.")

        except requests.exceptions.RequestException as e:
            print(f"Requests error fetching favicon from {favicon_url}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred while processing favicon for {favicon_url}: {e}")
    
    print(f"No valid favicon found or saved for {url}")
    return None

@app.route('/')
def index():
    conn = get_db_connection()
    search_query = request.args.get('q', '').strip()
    
    bookmarks = []
    
    current_engine_selection = request.args.get('engine')
    if search_query and current_engine_selection == 'my_bookmarks':
        bookmarks = conn.execute(
            'SELECT * FROM bookmarks WHERE name LIKE ? OR url LIKE ? ORDER BY name',
            ('%' + search_query + '%', '%' + search_query + '%')
        ).fetchall()
    else:
        bookmarks = conn.execute('SELECT * FROM bookmarks ORDER BY name').fetchall()

    conn.close()
    return render_template('index.html', bookmarks=bookmarks, search_query=search_query)

@app.route('/add', methods=('POST',))
def add_bookmark():
    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        fa_icon_class = request.form.get('fa_icon_class', '').strip()

        if not name or not url:
            print("Error: Name or URL is empty.")
            return "名称和URL都不能为空！", 400

        conn = get_db_connection()
        try:
            cursor = conn.execute('INSERT INTO bookmarks (name, url, fa_icon_class) VALUES (?, ?, ?)', (name, url, fa_icon_class if fa_icon_class else None))
            bookmark_id = cursor.lastrowid
            conn.commit()
            print(f"Bookmark added with ID: {bookmark_id}")

            favicon_path = fetch_and_cache_favicon(bookmark_id, url)
            if favicon_path:
                conn.execute('UPDATE bookmarks SET favicon_path = ? WHERE id = ?', (favicon_path, bookmark_id))
                conn.commit()
                print(f"Favicon path updated for bookmark {bookmark_id}: {favicon_path}")
            else:
                conn.execute('UPDATE bookmarks SET favicon_path = NULL WHERE id = ?', (bookmark_id,))
                conn.commit()
                print(f"No favicon found or saved for bookmark {bookmark_id}. favicon_path set to NULL.")

        except sqlite3.Error as e:
            print(f"Database error during add_bookmark: {e}")
            conn.rollback()
            return "数据库操作失败。", 500
        except Exception as e:
            print(f"An unexpected error occurred during add_bookmark: {e}")
            conn.rollback()
            return "添加收藏时发生未知错误。", 500
        finally:
            conn.close()
            
        return redirect(url_for('index'))

@app.route('/edit/<int:bookmark_id>', methods=('GET', 'POST'))
def edit_bookmark(bookmark_id):
    conn = get_db_connection()
    if request.method == 'POST':
        name = request.form['name']
        url = request.form['url']
        fa_icon_class = request.form.get('fa_icon_class', '').strip()

        if not name or not url:
            conn.close()
            return "名称和URL都不能为空！", 400

        try:
            old_bookmark = conn.execute('SELECT url, favicon_path FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
            old_url = old_bookmark['url'] if old_bookmark else None
            old_favicon_path = old_bookmark['favicon_path'] if old_bookmark else None

            conn.execute('UPDATE bookmarks SET name = ?, url = ?, fa_icon_class = ? WHERE id = ?', 
                         (name, url, fa_icon_class if fa_icon_class else None, bookmark_id))
            conn.commit()
            print(f"Bookmark {bookmark_id} updated successfully.")

            if old_url != url:
                if old_favicon_path:
                    favicon_filename = os.path.basename(old_favicon_path)
                    local_favicon_path = os.path.join(FAVICON_CACHE_DIR, favicon_filename)
                    if os.path.exists(local_favicon_path):
                        try:
                            os.remove(local_favicon_path)
                            print(f"Deleted old favicon file: {local_favicon_path}")
                        except OSError as e:
                            print(f"Error deleting old favicon file {local_favicon_path}: {e}")
                
                new_favicon_path = fetch_and_cache_favicon(bookmark_id, url)
                if new_favicon_path:
                    conn.execute('UPDATE bookmarks SET favicon_path = ? WHERE id = ?', (new_favicon_path, bookmark_id))
                    conn.commit()
                    print(f"New favicon path updated for bookmark {bookmark_id}: {new_favicon_path}")
                else:
                    conn.execute('UPDATE bookmarks SET favicon_path = NULL WHERE id = ?', (bookmark_id,))
                    conn.commit()
                    print(f"No new favicon found or saved for bookmark {bookmark_id}. favicon_path set to NULL.")

        except sqlite3.Error as e:
            print(f"Database error during edit_bookmark: {e}")
            conn.rollback()
            return "数据库操作失败。", 500
        except Exception as e:
            print(f"An unexpected error occurred during edit_bookmark: {e}")
            conn.rollback()
            return "编辑收藏时发生未知错误。", 500
        finally:
            conn.close()
        return redirect(url_for('index'))
    else: # GET request
        bookmark = conn.execute('SELECT * FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
        conn.close()
        if bookmark is None:
            return "收藏不存在。", 404
        return {'id': bookmark['id'], 'name': bookmark['name'], 'url': bookmark['url'], 'fa_icon_class': bookmark['fa_icon_class']}


@app.route('/delete/<int:bookmark_id>')
def delete_bookmark(bookmark_id):
    conn = get_db_connection()
    try:
        bookmark = conn.execute('SELECT favicon_path FROM bookmarks WHERE id = ?', (bookmark_id,)).fetchone()
        
        if bookmark and bookmark['favicon_path']:
            favicon_filename = os.path.basename(bookmark['favicon_path'])
            local_favicon_path = os.path.join(FAVICON_CACHE_DIR, favicon_filename)
            
            if os.path.exists(local_favicon_path):
                try:
                    os.remove(local_favicon_path)
                    print(f"Deleted favicon file: {local_favicon_path}")
                except OSError as e:
                    print(f"Error deleting favicon file {local_favicon_path}: {e}")
            else:
                print(f"Favicon file not found at {local_favicon_path} for bookmark {bookmark_id}.")
        else:
            print(f"No favicon path found for bookmark {bookmark_id} or bookmark not found in DB.")

        conn.execute('DELETE FROM bookmarks WHERE id = ?', (bookmark_id,))
        conn.commit()
        print(f"Bookmark {bookmark_id} deleted successfully from database.")

    except sqlite3.Error as e:
        print(f"Database error during deletion: {e}")
        conn.rollback()
    except Exception as e:
        print(f"An unexpected error occurred during delete_bookmark: {e}")
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/favicons/<filename>')
def serve_favicon(filename):
    print(f"Serving favicon: {filename} from {FAVICON_CACHE_DIR}")
    return send_from_directory(FAVICON_CACHE_DIR, filename)

@app.route('/shutdown', methods=['POST'])
def shutdown():
    # 仅允许来自本地的关闭请求，增加安全性
    if request.remote_addr != '127.0.0.1':
        return "Unauthorized", 401

    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    print("Flask server shutting down...")
    return "Server shutting down..."

if __name__ == '__main__':
    # 在打包后的程序中，这个 host 参数决定了服务器监听的地址
    # 保持 '127.0.0.1' 意味着只能在本地访问
    # 如果希望打包后也能在局域网访问，可以改为 '0.0.0.0'
    app.run(debug=True, host='0.0.0.0')