import os
import pandas as pd
import time
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


class PhoenixTextCrawler:
    def __init__(self, save_dir="test"):
        self.base_url = "https://mil.ifeng.com/shanklist/14-35083-"
        self.save_dir = save_dir
        self.excel_file = "test.xlsx"  # 改为test.xlsx
        self.text_data = []
        self.file_counter = 1

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

    def click_load_more_with_playwright(self):
        """使用Playwright模拟点击查看更多"""
        print("使用Playwright加载页面并点击查看更多...")

        with sync_playwright() as p:
            # 启动浏览器
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # 设置用户代理
            page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })

            # 访问页面
            print(f"访问页面: {self.base_url}")
            page.goto(self.base_url)
            time.sleep(3)

            all_articles = []
            seen_urls = set()

            # 获取初始文章
            initial_articles = self.extract_articles_from_playwright_page(page)
            for article in initial_articles:
                if article['url'] not in seen_urls:
                    seen_urls.add(article['url'])
                    all_articles.append(article)

            print(f"初始页面获取到 {len(initial_articles)} 篇文章")

            # 多次点击查看更多
            click_count = 0
            max_clicks = 10

            while len(all_articles) < 100 and click_count < max_clicks:
                click_count += 1
                print(f"\n第 {click_count} 次点击查看更多...")

                # 查找并点击查看更多按钮
                try:
                    # 等待按钮可点击
                    page.wait_for_selector('.news-stream-basic-more', timeout=5000)

                    # 点击查看更多按钮
                    page.click('.news-stream-basic-more')
                    print("点击查看更多成功")

                    # 等待新内容加载
                    time.sleep(3)

                    # 获取新加载的文章
                    new_articles = self.extract_articles_from_playwright_page(page)

                    # 添加新文章
                    new_count = 0
                    for article in new_articles:
                        if article['url'] not in seen_urls and len(all_articles) < 100:
                            seen_urls.add(article['url'])
                            all_articles.append(article)
                            new_count += 1

                    print(f"新增 {new_count} 篇文章，累计 {len(all_articles)} 篇")

                    # 如果没有新文章，停止尝试
                    if new_count == 0:
                        print("没有新文章加载，停止点击")
                        break

                except Exception as e:
                    print(f"点击查看更多失败: {e}")
                    break

            print(f"通过 {click_count} 次点击查看更多，总共获取到 {len(all_articles)} 篇文章")

            # 关闭浏览器
            browser.close()

            return all_articles

    def extract_articles_from_playwright_page(self, page):
        """从Playwright页面提取文章"""
        # 获取页面HTML
        html_content = page.content()
        return self.extract_articles_from_html(html_content)

    def extract_articles_from_html(self, html_content):
        """从HTML中提取文章"""
        articles = []
        soup = BeautifulSoup(html_content, 'html.parser')

        # 查找新闻列表
        news_items = soup.find_all('li', class_='news_item')

        for item in news_items:
            try:
                link = item.find('a', class_='news-stream-newsStream-image-link')
                if not link or not link.get('href'):
                    continue

                url = link.get('href')
                if not url.startswith('http'):
                    url = urljoin('https://mil.ifeng.com', url)

                title_elem = item.find('h2') or item.find('a', title=True)
                title = title_elem.get_text().strip() if title_elem else ""

                time_elem = item.find('time')
                news_time = time_elem.get_text().strip() if time_elem else ""

                articles.append({
                    'url': url,
                    'title': title,
                    'news_time': news_time,
                    'id': item.get('data-id', ''),
                    'source': 'playwright'
                })
            except:
                continue

        return articles

    def get_page_content(self, url):
        """使用requests获取文章内容"""
        import requests
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        })

        try:
            response = session.get(url, timeout=15)
            response.encoding = 'utf-8'
            return response.text
        except Exception as e:
            print(f"请求页面失败: {e}")
            return None

    def extract_text_from_article(self, html_content, article_info):
        """从文章页面提取文本信息"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            title = soup.find('h1')
            title_text = title.get_text().strip() if title else article_info['title']

            time_elem = soup.find('span', class_='time') or soup.find('div', class_='time')
            time_text = time_elem.get_text().strip() if time_elem else article_info.get('news_time', '')

            content_selectors = [
                '.article-content', '.article-body', '.content', '.main-content', '.text',
                'div[class*="content"]', 'div[class*="text"]'
            ]

            content = None
            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    break

            if not content:
                paragraphs = soup.find_all('p')
                meaningful_paragraphs = []
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 20:
                        meaningful_paragraphs.append(text)

                content_text = '\n\n'.join(meaningful_paragraphs) if meaningful_paragraphs else "无法提取正文内容"
            else:
                for element in content.find_all(['script', 'style']):
                    element.decompose()
                content_text = content.get_text().strip()

            content_text = re.sub(r'\s+', ' ', content_text).strip()

            return {
                'title': title_text,
                'time': time_text,
                'content': content_text,
                'url': article_info['url']
            }

        except Exception as e:
            print(f"提取文本失败: {e}")
            return {
                'title': article_info['title'],
                'time': article_info.get('news_time', ''),
                'content': f"提取失败: {str(e)}",
                'url': article_info['url']
            }

    def save_text_to_file(self, text_info):
        """将文本保存到文件"""
        try:
            filename = f"{self.file_counter:03d}.txt"
            filepath = os.path.join(self.save_dir, filename)

            file_content = f"标题: {text_info['title']}\n"
            file_content += f"时间: {text_info['time']}\n"
            file_content += f"原文链接: {text_info['url']}\n"
            file_content += "=" * 50 + "\n"
            file_content += text_info['content']

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)

            file_info = {
                'file_number': self.file_counter,
                'title': text_info['title'],
                'time': text_info['time'],
                'url': text_info['url'],
                'file_path': os.path.abspath(filepath),
                'filename': filename,
                'save_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'content_length': len(text_info['content'])
            }

            print(f"  ✓ 文本保存成功: {filename} (长度: {len(text_info['content'])} 字符)")
            self.file_counter += 1

            return file_info

        except Exception as e:
            print(f"  ✗ 保存文件失败: {e}")
            return None

    def crawl_articles_text(self):
        """爬取文章文本"""
        print("开始爬取凤凰军事新闻文本...")
        print(f"目标网址: {self.base_url}")
        print("目标文章数量: 100 篇")
        print("使用Playwright模拟浏览器点击查看更多...")

        # 使用Playwright获取所有文章
        articles = self.click_load_more_with_playwright()
        if not articles:
            print("未找到文章列表")
            return

        total_files = 0

        for i, article in enumerate(articles):
            if total_files >= 100:
                break

            print(f"\n处理第 {i + 1}/{len(articles)} 篇文章")
            print(f"标题: {article['title']}")

            html_content = self.get_page_content(article['url'])
            if not html_content:
                print("无法获取文章内容，跳过")
                continue

            text_info = self.extract_text_from_article(html_content, article)

            if not text_info or not text_info.get('content') or text_info['content'] in ["无法提取正文内容",
                                                                                         "提取失败"]:
                print("本文未提取到有效文本，跳过")
                continue

            result = self.save_text_to_file(text_info)
            if result:
                self.text_data.append(result)
                total_files += 1

            if i < len(articles) - 1:
                time.sleep(1)

        self.save_to_excel()

        print(f"\n爬取完成！")
        print(f"处理文章: {len(articles)} 篇")
        print(f"保存文件: {total_files} 个")
        print(f"文本文件保存在: {os.path.abspath(self.save_dir)} 文件夹")
        print(f"路径列表保存在: {self.excel_file}")

    def save_to_excel(self):
        """将文件路径保存到Excel"""
        if self.text_data:
            path_data = [{'absolute_path': item['file_path']} for item in self.text_data]
            df = pd.DataFrame(path_data)
            df.to_excel(self.excel_file, index=False)
            print(f"文本文件绝对路径已保存到: {self.excel_file}")
        else:
            print("没有数据可保存")


if __name__ == "__main__":
    crawler = PhoenixTextCrawler("test")  # 文件夹名称改为test
    crawler.crawl_articles_text()