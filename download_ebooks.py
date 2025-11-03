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
        downloads_path=OUTPUT_PATH,
        # args=['--blink-settings=imagesEnabled=false'] # 默认不加载图片，提升速度
    )
    context = browser.new_context(accept_downloads=True, timeout=60_000)
    page = context.new_page()
    page.route("**/*", lambda route: route.abort() if route.request.resource_type == "image" else route.continue_())
    page.goto(url)
    datetime_now = datetime.now().astimezone(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d%H%M%S')

    print("正在登录ZLibrary...")
    page.get_by_role("link", name="Log In").click()
    page.get_by_role("textbox", name="Email").click()
    page.get_by_role("textbox", name="Email").fill(ZLIBRARY_USERNAME)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(ZLIBRARY_PASSWORD)
    page.get_by_role("button", name="Log In").click()
    # 确保登录成功
    expect(page.get_by_role("button", name=" 导入数据")).to_be_visible()


    print("登录成功，开始搜索电子书...")
    book_info = pd.DataFrame()
    page_search = context.new_page()
    search_url = f'{url}/s/{book_name}?selected_content_types[]={content_type}'
    print("搜索链接: ", search_url)
    resp = page_search.goto(search_url)
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

        # 截图保存搜索结果页面，循环向下滚动页面，以加载完全
        for _ in range(10):
            time.sleep(3)
            page_search.keyboard.press("PageDown")
            page_search.wait_for_load_state("networkidle")
        page_search.screenshot(path=os.path.join(OUTPUT_PATH, f'{book_name}_screenshot_{datetime_now}.png'), full_page=True)

    if book_info.empty:
        print("未找到相关电子书: ", book_name)
    else:
        print(f"找到相关电子书 {len(book_info)} 本")
        book_info.to_csv(os.path.join(OUTPUT_PATH, f'{book_name}_search_results_{datetime_now}.csv'), index=False, encoding='utf-8-sig')

    print("打开书籍详情页面，解析下载链接...")
    page_detail = context.new_page()
    for idx, row in book_info.head(auto_download_num).iterrows():
        id, title, author, extension, detail = row['id'], row['title'], row['author'], row['extension'], row['href']
        detail_url = f"{url}{detail}"
        
        print(f"正在解析第 {idx+1} 本: ", title, author, extension, detail_url)
        page_detail.route("**/*", lambda route: route.abort() if route.request.resource_type == "image" else route.continue_())
        page_detail.goto(detail_url)
        resp = page_detail.goto(detail_url)
        if resp.status != 200:
            print(f"请求错误，状态码: {resp.status}")
        else:
            # 解析书籍详情页面
            soup = BeautifulSoup(resp.text(), "lxml")
            download_link_tag = soup.select_one('a.btn.btn-default.addDownloadedBook')
            if not download_link_tag:
                print("没有解析到指定的下载链接。")
            else:
                href_value = download_link_tag.get('href')
                download_url = f"{url}{href_value}"
                print(f"成功解析出下载链接: {download_url}")
                page_download = context.new_page()

                print("开始下载文件...")
                page_download.on("download", lambda download: print("捕获下载:", download.url))
                with page_download.expect_download() as download_info:
                    page_download.goto(download_url)  # 或直接 click 触发下载的元素
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
    else:
        raise ValueError("请在 config.json 文件中配置 ZLIBRARY_USERNAME 和 ZLIBRARY_PASSWORD")

    zlibrary_url = get_zlibrary_website()
    with sync_playwright() as playwright:
        run(playwright, zlibrary_url, ebook_name, headless=False)


if __name__ == "__main__":
    ebook_name = "我与地坛"
    download_ebook(ebook_name)




