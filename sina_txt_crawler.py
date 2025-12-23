import requests
import os
import pandas as pd
import time
import urllib3
from bs4 import BeautifulSoup
import re
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
from datetime import datetime

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SinaMilitaryTextCrawler:
    def __init__(self):
        # 使用固定的test文件夹
        self.save_folder = "test"
        os.makedirs(self.save_folder, exist_ok=True)

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Referer': 'https://mil.news.sina.com.cn/',
        }

        self.processed_articles = set()
        self.text_data = []

    def click_load_more_with_playwright(self, target_count=100):
        """使用Playwright获取文章"""
        print(" 使用Playwright获取文章...")

        all_articles = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=self.headers['User-Agent']
            )
            page = context.new_page()

            try:
                page.goto("https://mil.news.sina.com.cn/", timeout=60000)
                time.sleep(5)

                page.wait_for_selector('.ty-cardlist-w', timeout=10000)
                print("   页面加载完成")

                click_count = 0
                consecutive_failures = 0
                max_consecutive_failures = 5
                max_clicks = 3

                while (click_count < max_clicks and
                       consecutive_failures < max_consecutive_failures):

                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)

                    current_articles = self.extract_articles_from_playwright_page(page)

                    seen_urls = {article['link'] for article in all_articles}
                    new_articles = [article for article in current_articles if article['link'] not in seen_urls]

                    if new_articles:
                        all_articles.extend(new_articles)
                        print(f"   滚动获取: {len(new_articles)}篇新文章 (总计: {len(all_articles)}篇)")
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        print(f"   滚动未发现新文章，连续失败: {consecutive_failures}次")

                    clicked = False
                    try:
                        js_script = """
                        (function() {
                            const buttons = [
                                document.querySelector('.cardlist-a__more-c'),
                                document.querySelector('[node-type="cardlist-reload-bottom"]'),
                                document.querySelector('div[data-sudaclick*="feed_refresh"]'),
                                document.querySelector('.load-more'),
                                document.querySelector('.more-btn'),
                                document.querySelector('.ty-card-ft-more')
                            ].filter(btn => btn !== null);

                            for (let btn of buttons) {
                                try {
                                    btn.scrollIntoView({behavior: 'smooth', block: 'center'});
                                    const rect = btn.getBoundingClientRect();
                                    const isVisible = rect.top >= 0 && rect.left >= 0 && 
                                                    rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) && 
                                                    rect.right <= (window.innerWidth || document.documentElement.clientWidth);

                                    if (isVisible) {
                                        btn.click();
                                        return true;
                                    } else {
                                        const clickEvent = new MouseEvent('click', {
                                            bubbles: true,
                                            cancelable: true,
                                            view: window,
                                            buttons: 1
                                        });
                                        btn.dispatchEvent(clickEvent);
                                        return true;
                                    }
                                } catch (e) {
                                    continue;
                                }
                            }
                            return false;
                        })();
                        """
                        result = page.evaluate(js_script)
                        if result:
                            clicked = True
                            click_count += 1
                            print(f"   点击成功 (第{click_count}次)")

                            print(f"   等待新内容加载...")
                            time.sleep(5)

                            for i in range(3):
                                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                                time.sleep(2)
                                print(f"   滚动加载第{i + 1}次")

                            time.sleep(3)

                            post_click_articles = self.extract_articles_from_playwright_page(page)
                            post_seen_urls = {article['link'] for article in all_articles}
                            post_new_articles = [article for article in post_click_articles if
                                                 article['link'] not in post_seen_urls]

                            if post_new_articles:
                                all_articles.extend(post_new_articles)
                                print(f"   点击后获取: {len(post_new_articles)}篇新文章 (总计: {len(all_articles)}篇)")

                            consecutive_failures = 0

                    except Exception as e:
                        print(f"   点击出错: {e}")

                    if not clicked:
                        consecutive_failures += 1
                        print(f"   未找到可点击按钮，连续失败: {consecutive_failures}次")

                    time.sleep(2)
                    print(f"   当前进度: {len(all_articles)}篇 / 目标: {target_count}篇, 点击次数: {click_count}/{max_clicks}")

                print(f"   最终获取: {len(all_articles)}篇文章")
                print(f"   总点击次数: {click_count}次")

            except Exception as e:
                print(f"   Playwright执行出错: {e}")
            finally:
                browser.close()

        return all_articles[:target_count]

    def extract_articles_from_playwright_page(self, page):
        """从Playwright页面提取文章信息"""
        try:
            html_content = page.content()
            soup = BeautifulSoup(html_content, 'html.parser')

            articles = []

            selectors = [
                '.ty-cardlist-w .ty-card',
                '.ty-card',
                '.news-item',
                '.news-list li',
                '.feed-card-item',
                '[data-sudaclick*="news"]'
            ]

            news_items = []
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    news_items.extend(items)
                    break

            if not news_items:
                news_items = soup.find_all('div', class_=re.compile(r'card|news|item'))

            for item in news_items:
                try:
                    link = item.find('a', href=True)
                    if not link:
                        continue

                    url = link.get('href')
                    if not url:
                        continue

                    if not url.startswith('http'):
                        url = urljoin('https://mil.news.sina.com.cn/', url)

                    if not any(domain in url for domain in ['.sina.com.cn', '.sina.cn']):
                        continue

                    title = ""
                    for tag in ['h1', 'h2', 'h3', 'h4']:
                        title_elem = item.find(tag)
                        if title_elem:
                            title_text = title_elem.get_text().strip()
                            if title_text and len(title_text) > 5:
                                title = title_text
                                break

                    if not title:
                        title_text = link.get_text().strip()
                        if title_text and len(title_text) > 5:
                            title = title_text

                    if not title or len(title) < 5:
                        continue

                    time_elem = item.find('time') or item.find(class_=re.compile(r'time|date'))
                    news_time = time_elem.get_text().strip() if time_elem else ""

                    articles.append({
                        'title': title,
                        'link': url,
                        'time': news_time
                    })

                except Exception:
                    continue

            return articles

        except Exception:
            return []

    def get_article_content(self, article_url):
        """获取文章详情页内容"""
        try:
            response = requests.get(article_url, headers=self.headers, timeout=10, verify=False)
            response.encoding = 'utf-8'
            return response.text if response.status_code == 200 else None
        except Exception:
            return None

    def extract_text_from_article(self, html_content, article_info):
        """从文章页面提取文本信息"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            title_elem = soup.find('h1')
            title = title_elem.get_text().strip() if title_elem else article_info['title']

            time_elem = soup.find('span', class_='time') or soup.find(class_=re.compile(r'time|date'))
            publish_time = time_elem.get_text().strip() if time_elem else article_info.get('time', '')

            source_elem = soup.find(class_=re.compile(r'source|来源'))
            source = source_elem.get_text().strip() if source_elem else "新浪军事"

            content_selectors = [
                'div.article-content',
                'div.article-body',
                'div#artibody',
                'div.content',
                'div.main-content',
                'div.article'
            ]

            content_text = ""
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    for element in content_elem.find_all(['script', 'style']):
                        element.decompose()

                    paragraphs = content_elem.find_all('p')
                    if paragraphs:
                        content_text = '\n\n'.join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
                        break

            if not content_text:
                paragraphs = soup.find_all('p')
                meaningful_paragraphs = []
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 20:
                        meaningful_paragraphs.append(text)
                content_text = '\n\n'.join(meaningful_paragraphs)

            content_text = re.sub(r'\s+', ' ', content_text).strip()

            return {
                'title': title,
                'publish_time': publish_time,
                'source': source,
                'content': content_text,
                'url': article_info['link']
            }

        except Exception as e:
            return {
                'title': article_info['title'],
                'publish_time': article_info.get('time', ''),
                'source': '新浪军事',
                'content': f"提取失败: {str(e)}",
                'url': article_info['link']
            }

    def save_text_to_file(self, text_info, file_number):
        """将文本保存到文件"""
        try:
            # 添加时间戳避免文件名冲突
            timestamp = datetime.now().strftime("%H%M%S")
            filename = f"{file_number:03d}_{timestamp}.txt"
            filepath = os.path.join(self.save_folder, filename)

            file_content = f"标题: {text_info['title']}\n"
            file_content += f"发布时间: {text_info['publish_time']}\n"
            file_content += f"来源: {text_info['source']}\n"
            file_content += f"原文链接: {text_info['url']}\n"
            file_content += "=" * 50 + "\n\n"
            file_content += text_info['content']

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)

            file_info = {
                'file_number': file_number,
                'title': text_info['title'],
                'publish_time': text_info['publish_time'],
                'source': text_info['source'],
                'url': text_info['url'],
                'file_path': os.path.abspath(filepath),
                'filename': filename,
                'content_length': len(text_info['content'])
            }

            return file_info

        except Exception:
            return None

    def crawl_articles_text(self, target_count=100):
        """爬取文章文本"""
        print(f"目标: {target_count}篇文章")
        print("获取文章中...")

        articles = self.click_load_more_with_playwright(target_count=target_count)

        if not articles:
            print("抱歉，没有获取到文章")
            return 0

        print(f"开始处理 {len(articles)} 篇文章...")

        file_counter = 1
        success_count = 0

        for i, article in enumerate(articles):
            if success_count >= target_count:
                break

            title = article.get('title', '').strip()
            article_url = article.get('link', '')

            if not title or not article_url:
                continue

            if article_url.startswith('//'):
                article_url = 'https:' + article_url

            if article_url in self.processed_articles:
                continue

            self.processed_articles.add(article_url)

            print(f"  [{i + 1:2d}/{len(articles)}] 处理: {title[:30]}...")

            html_content = self.get_article_content(article_url)
            if not html_content:
                print(f"    获取内容失败")
                continue

            text_info = self.extract_text_from_article(html_content, article)

            if not text_info.get('content') or len(text_info['content']) < 50:
                print(f"    内容过短或无效")
                continue

            file_info = self.save_text_to_file(text_info, file_counter)
            if file_info:
                self.text_data.append(file_info)
                success_count += 1
                file_counter += 1
                print(f"    保存成功: {file_info['filename']} (长度: {file_info['content_length']}字符)")
            else:
                print("    保存失败")

            print(f"    进度: {success_count}/{target_count}")
            time.sleep(1)

        return success_count

    def save_to_excel(self):
        """将文件路径保存到Excel - 只保存绝对地址"""
        if not self.text_data:
            return None

        # 只保存绝对路径
        df = pd.DataFrame({
            'absolute_path': [item['file_path'] for item in self.text_data]
        })

        excel_filename = f"test.xlsx"
        excel_path = os.path.join(os.getcwd(), excel_filename)

        try:
            df.to_excel(excel_path, index=False)
            return os.path.abspath(excel_path)
        except Exception:
            return None

    def run(self, target_count=100):
        """运行爬虫"""
        print("=== 新浪军事文本爬虫 ===")
        start_time = time.time()

        success_count = self.crawl_articles_text(target_count)
        excel_path = self.save_to_excel()

        end_time = time.time()
        elapsed_time = end_time - start_time

        print(f"\n爬取完成!")
        print(f"   耗时: {elapsed_time:.1f}秒")
        print(f"   成功保存: {success_count}篇文章")
        if excel_path:
            print(f"   保存到: {excel_path}")

        return {
            'success': success_count > 0,
            'article_count': success_count,
            'excel_path': excel_path
        }


def main():
    """主函数"""
    crawler = SinaMilitaryTextCrawler()
    result = crawler.run(target_count=100)

    if result['success']:
        print(f"\n成功获取 {result['article_count']} 篇文章")
    else:
        print(f"\n抱歉，爬取失败")


if __name__ == "__main__":
    main()