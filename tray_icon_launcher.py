import sys
import os
import subprocess
import time
import requests
from pystray import Icon, Menu, MenuItem
from PIL import Image, ImageDraw # 导入 ImageDraw 用于绘制默认图标

# --- 配置 ---
# Flask 应用的可执行文件名称 (这是您用 PyInstaller 打包 app.py 后生成的文件名)
FLASK_APP_EXE_NAME = "MyWebBookmarkApp" 
FLASK_APP_HOST = "127.0.0.1"
FLASK_APP_PORT = 5000
FLASK_APP_URL = f"http://{FLASK_APP_HOST}:{FLASK_APP_PORT}"
FLASK_SHUTDOWN_URL = f"http://{FLASK_APP_HOST}:{FLASK_APP_PORT}/shutdown"

# 获取当前 launcher 可执行文件所在的目录
if getattr(sys, 'frozen', False):
    APP_ROOT = os.path.abspath(os.path.dirname(sys.argv[0]))
    FLASK_APP_EXECUTABLE = os.path.join(APP_ROOT, FLASK_APP_EXE_NAME)
else:
    # 用于在开发环境中直接运行 .py 脚本时的路径
    FLASK_APP_EXECUTABLE = os.path.join(os.path.dirname(__file__), 'app.py')
    # 如果是 .py 脚本，需要用 python 解释器启动
    FLASK_APP_COMMAND = [sys.executable, FLASK_APP_EXECUTABLE]

# --- 全局变量 ---
flask_process = None
tray_icon_instance = None # 重命名以避免与 pystray.Icon 冲突

# --- 函数 ---

def generate_default_icon():
    # 简单图标：一个蓝色的正方形，中间有一个白色的圆圈
    width = 64
    height = 64
    image = Image.new("RGB", (width, height), color=(0, 0, 255)) # 蓝色背景
    
    # 绘制一个白色的圆圈
    draw = ImageDraw.Draw(image)
    radius = int(width / 3)
    center_x, center_y = width // 2, height // 2
    draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), fill=(255, 255, 255))
    
    return image


def launch_flask_app():
    global flask_process
    print(f"尝试启动 Flask 应用: {FLASK_APP_EXECUTABLE}")
    try:
        if getattr(sys, 'frozen', False):
            # 当打包成可执行文件时，直接执行 Flask 应用可执行文件
            # creationflags=subprocess.CREATE_NO_WINDOW 隐藏 Windows 上的命令行窗口
            flask_process = subprocess.Popen([FLASK_APP_EXECUTABLE], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        else:
            # 在开发环境中，使用 Python 解释器启动 Flask 脚本
            flask_process = subprocess.Popen(FLASK_APP_COMMAND)
        print(f"Flask 应用已启动，PID: {flask_process.pid}")
        
        # 等待 Flask 应用启动并响应
        start_time = time.time()
        max_wait_time = 30 # 最大等待时间 30 秒
        while time.time() - start_time < max_wait_time:
            try:
                # 尝试访问 Flask 应用的 URL，检查是否响应
                requests.get(FLASK_APP_URL, timeout=1)
                print("Flask 应用已响应。")
                return True
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                print("Flask 应用尚未响应，等待中...")
                time.sleep(0.5) # 等待 0.5 秒后重试
            except Exception as e:
                print(f"检查 Flask 状态时出错: {e}")
                time.sleep(0.5)
        print(f"Flask 应用未在 {max_wait_time} 秒内响应。")
        return False
    except Exception as e:
        print(f"启动 Flask 应用失败: {e}")
        return False

def stop_flask_app():
    global flask_process
    print("尝试停止 Flask 应用...")
    if flask_process:
        try:
            # 向 Flask 应用的 /shutdown 路由发送 POST 请求以优雅关闭
            requests.post(FLASK_SHUTDOWN_URL, timeout=5)
            print("已向 Flask 应用发送关闭信号。")
            time.sleep(1) # 给 Flask 应用一点时间来关闭
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"Flask 应用已断开连接或关闭请求超时: {e}。强制终止。")
        except Exception as e:
            print(f"发送关闭请求时出错: {e}。强制终止。")
        
        # 如果 Flask 进程仍然在运行，则强制终止
        if flask_process.poll() is None:
            print("Flask 进程仍在运行，尝试终止...")
            flask_process.terminate() # 发送 SIGTERM 信号
            try:
                flask_process.wait(timeout=5) # 等待进程终止
            except subprocess.TimeoutExpired:
                print("Flask 进程未在规定时间内终止，强制杀死...")
                flask_process.kill() # 发送 SIGKILL 信号
        flask_process = None
    print("Flask 应用已停止。")

def open_app_in_browser(icon, item):
    import webbrowser
    webbrowser.open(FLASK_APP_URL)
    print(f"在浏览器中打开 {FLASK_APP_URL}。")

def exit_app(icon, item):
    print("退出托盘应用程序。")
    stop_flask_app()
    icon.stop() # 停止 pystray 图标
    sys.exit(0) # 退出整个 launcher 进程

def setup_tray_icon():
    # 尝试加载自定义图标文件，否则生成一个默认图标
    icon_path = os.path.join(APP_ROOT if getattr(sys, 'frozen', False) else os.path.dirname(__file__), "app_icon.png") # 推荐 .png 或 .ico 格式
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        print("图标文件未找到。正在生成默认图标。")
        image = generate_default_icon()

    # 创建托盘菜单
    menu = Menu(MenuItem('打开网页收藏', open_app_in_browser),
                MenuItem('退出应用', exit_app))
    
    global tray_icon_instance
    tray_icon_instance = Icon("MyBookmarkAppTray", image, "网页收藏应用", menu)
    
    # 运行托盘图标 (这是一个阻塞调用，直到图标被停止)
    tray_icon_instance.run()

# --- 主程序入口 ---
if __name__ == '__main__':
    print("托盘应用程序启动中...")
    
    # 1. 启动 Flask 应用
    if not launch_flask_app():
        print("无法启动 Flask 应用。退出托盘程序。")
        sys.exit(1)

    # 2. 设置并运行系统托盘图标
    setup_tray_icon()

    print("托盘应用程序已退出。")