import os
import time
import json
import math
import random
import pytz
import requests
import numpy as np
import pandas as pd
from lxml import etree
from datetime import datetime, timedelta
from zlibrary_helper import get_zlibrary_website
import pathlib
from playwright.sync_api import Playwright, sync_playwright, expect
from bs4 import BeautifulSoup
from urllib.parse import quote


BASE_PATH, OUTPUT_PATH, ZLIBRARY_USERNAME, ZLIBRARY_PASSWORD, HEADERS, COOKIES = None, None, None, None, {}, {}


def update_cookies(context):
    cookies = context.cookies()

    print(cookies)
    global HEADERS, COOKIES
    COOKIES = {}
    for item in cookies:
        COOKIES[item['name']] = item['value']
    HEADERS['Cookie'] = "; ".join([f"{k}={v}" for k, v in cookies.items() if k in ['CPL-coros-region', 'CPL-coros-token', 'tfstk']])
    
    # 保存cookies和headers到文件
    with open(os.path.join(OUTPUT_PATH, 'cookies.json'), 'w', encoding='utf-8') as f:
        json.dump(COOKIES, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUTPUT_PATH, 'headers.json'), 'w', encoding='utf-8') as f:
        json.dump(HEADERS, f, ensure_ascii=False, indent=2)


def run(playwright: Playwright, url, book_name, content_type='book', file_type='epub', auto_download_num=3, headless=False):
    """
    使用 Playwright 自动化登录 ZLibrary 并下载电子书
    :param playwright: Playwright 对象
    :param url: ZLibrary 网站 URL
    :param book_name: 电子书名称
    :param content_type: 内容类型，默认为 'book'
    :param file_type: 文件类型，默认为 'epub'
    :param auto_download_num: 自动下载的电子书数量，默认为 3
    :param headless: 是否无头模式运行浏览器，默认为 False
    """
    
    browser = playwright.chromium.launch(
        headless=headless,
        # args=['--blink-settings=imagesEnabled=false'] # 默认不加载图片，提升速度
    )
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    datetime_now = datetime.now().astimezone(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d%H%M%S')

    print("正在登录ZLibrary...")
    page.get_by_role("link", name="Log In").click()
    page.get_by_role("textbox", name="Email").click()
    page.get_by_role("textbox", name="Email").fill(ZLIBRARY_USERNAME)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(ZLIBRARY_PASSWORD)
    page.get_by_role("button", name="Log In").click()


    print("登录成功，开始搜索电子书...")
    book_info = pd.DataFrame()
    # resp = page.goto(f'{url}/s/{book_name}?selected_content_types[]={content_type}') #, wait_until="commit")
    resp = page.goto(quote(f'{url}/s/{book_name}', safe=":/?#[]@!$&'()*+,;="))
    if resp.status != 200:
        print(f"请求错误，状态码: {resp.status}")
    else:
        # 解析搜索结果页面
        soup = BeautifulSoup(resp.text(), "lxml")
        records = []
        for card in soup.find_all("z-bookcard"):
            attrs = card.attrs.copy()
            for slot in ("title", "author", "note"):
                node = card.find(attrs={"slot": slot})
                attrs[slot] = node.get_text(strip=True) if node else None
            records.append(attrs)
        book_info = pd.DataFrame(records)

        # 截图保存搜索结果页面
        page.evaluate("window.scrollTo(0, 500)")
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(OUTPUT_PATH, f'{book_name}_screenshot_{datetime_now}.png'), full_page=False)

    if book_info.empty:
        print("未找到相关电子书: ", book_name)
    else:
        print(f"找到相关电子书 {len(book_info)} 本")

    print("开始下载电子书...")
    for idx, row in book_info.head(auto_download_num).iterrows():
        print(f"正在下载第 {idx+1} 本: ", row['title'])
        id, title, author, extension, download = row['id'], row['title'], row['author'], row['extension'], row['download']
        page.goto(f"{url}{download}")
        with page.expect_download() as download_info:
            download = download_info.value
            output_filename = os.path.join(OUTPUT_PATH, f'{book_name}_{id}_{title}_{author}_{datetime_now}.{extension}')
            download.save_as(path=output_filename)
            print("文件已保存至: ", output_filename)

    page.close()


def download_ebook(ebook_name):
    """
    Downloads an ebook from ZLibrary given its ID and saves it to the specified path.
    """
    global BASE_PATH, OUTPUT_PATH, ZLIBRARY_USERNAME, ZLIBRARY_PASSWORD, HEADERS, COOKIES
    
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_PATH = os.path.join(BASE_PATH, "output") 
    if not os.path.exists(OUTPUT_PATH):
        os.makedirs(OUTPUT_PATH)
    if os.path.exists(os.path.join(BASE_PATH, 'headers.json')):
        with open(os.path.join(BASE_PATH, 'headers.json'), 'r') as f:
            HEADERS = json.load(f)
    if os.path.exists(os.path.join(BASE_PATH, 'cookies.json')):
        with open(os.path.join(BASE_PATH, 'cookies.json'), 'r') as f:
            COOKIES = json.load(f)
    if os.path.exists(os.path.join(BASE_PATH, 'config.json')):
        with open(os.path.join(BASE_PATH, 'config.json'), 'r') as f:
            config = json.load(f)
        ZLIBRARY_USERNAME = config.get('ZLIBRARY_USERNAME')
        ZLIBRARY_PASSWORD = config.get('ZLIBRARY_PASSWORD')

    zlibrary_url = get_zlibrary_website()
    with sync_playwright() as playwright:
        run(playwright, zlibrary_url, ebook_name, headless=True)





if __name__ == "__main__":
    ebook_name = "我与地坛"
    download_ebook(ebook_name)




