# sina_image_crawler.py
import requests
import os
import pandas as pd
import time
import urllib3
from bs4 import BeautifulSoup
import re
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
import hashlib

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SinaMilitaryImageCrawler:
    def __init__(self):
        self.images_folder = "test"
        os.makedirs(self.images_folder, exist_ok=True)

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Referer': 'https://mil.news.sina.com.cn/',
        }

        self.processed_articles = set()
        self.processed_images = set()
        self.image_data = []  # 存储图片路径的列表
        self.image_count = 0
        self.max_images = 100

    def click_load_more_with_playwright(self):
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
                max_clicks = 10

                while (click_count < max_clicks and
                       consecutive_failures < max_consecutive_failures and
                       self.image_count < self.max_images):

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

                    if self.image_count >= self.max_images:
                        break

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
                    print(
                        f"   当前进度: 文章{len(all_articles)}篇, 图片{self.image_count}/{self.max_images}张, 点击次数: {click_count}/{max_clicks}")

                print(f"   最终获取: {len(all_articles)}篇文章")
                print(f"   总点击次数: {click_count}次")

            except Exception as e:
                print(f"   Playwright执行出错: {e}")
            finally:
                browser.close()

        return all_articles

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

                    articles.append({
                        'title': title,
                        'link': url,
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

    def download_image(self, img_url):
        """下载图片"""
        if self.image_count >= self.max_images:
            return None

        try:
            img_hash = hashlib.md5(img_url.encode()).hexdigest()
            if img_hash in self.processed_images:
                return None

            img_headers = self.headers.copy()
            img_headers['Accept'] = 'image/webp,image/apng,image/*,*/*;q=0.8'

            response = requests.get(img_url, headers=img_headers, timeout=10, verify=False)
            if response.status_code == 200:
                if len(response.content) < 5000:
                    return None

                file_extension = os.path.splitext(img_url.split('?')[0])[1]
                if not file_extension or len(file_extension) > 5:
                    file_extension = '.jpg'

                filename = f"{self.image_count + 1:03d}{file_extension}"
                filepath = os.path.join(self.images_folder, filename)

                with open(filepath, 'wb') as f:
                    f.write(response.content)

                self.processed_images.add(img_hash)
                self.image_count += 1

                # 直接存储绝对路径字符串
                absolute_path = os.path.abspath(filepath)
                return absolute_path

        except Exception as e:
            print(f"    图片下载失败: {e}")

        return None

    def extract_images_from_article(self, html_content, article_title):
        """从文章页面提取图片"""
        if self.image_count >= self.max_images:
            return []

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            image_paths = []

            img_selectors = [
                'div.article-content img',
                'div.article-body img',
                'div#artibody img',
                'div.content img',
                'div.main-content img',
                'div.article img'
            ]

            for selector in img_selectors:
                img_tags = soup.select(selector)
                for img_tag in img_tags:
                    if self.image_count >= self.max_images:
                        break

                    img_src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-original')
                    if not img_src:
                        continue

                    if not img_src.startswith('http'):
                        img_src = urljoin('https://mil.news.sina.com.cn/', img_src)

                    if any(keyword in img_src.lower() for keyword in ['icon', 'logo', 'spacer', 'ad', 'gif']):
                        continue

                    if 'sina.com.cn/images' in img_src:
                        continue

                    image_path = self.download_image(img_src)
                    if image_path:
                        image_paths.append(image_path)
                        print(f"    📷 下载图片: {self.image_count:03d}.jpg")

            return image_paths

        except Exception as e:
            print(f"    提取图片失败: {e}")
            return []

    def crawl_images(self):
        """爬取图片"""
        print(f"目标: {self.max_images}张图片")
        print("获取文章中...")

        articles = self.click_load_more_with_playwright()

        if not articles:
            print("抱歉，没有获取到文章")
            return 0

        print(f"开始处理 {len(articles)} 篇文章中的图片...")

        processed_urls = set()
        processed_titles = set()

        for i, article in enumerate(articles):
            if self.image_count >= self.max_images:
                break

            title = article.get('title', '').strip()
            article_url = article.get('link', '')

            if not title or not article_url:
                continue

            if article_url.startswith('//'):
                article_url = 'https:' + article_url

            if article_url in processed_urls:
                continue

            title_key = re.sub(r'[^\w\u4e00-\u9fa5]', '', title.lower())
            if title_key in processed_titles:
                continue

            processed_urls.add(article_url)
            processed_titles.add(title_key)

            print(f"  [{i + 1:2d}/{len(articles)}] 处理文章: {title[:30]}...")

            html_content = self.get_article_content(article_url)
            if not html_content:
                print(f"    获取内容失败")
                continue

            image_paths = self.extract_images_from_article(html_content, title)

            if image_paths:
                # 直接扩展路径列表
                self.image_data.extend(image_paths)
                print(f"    从此文章获取 {len(image_paths)} 张图片")

            print(f"    进度: {self.image_count}/{self.max_images} 张图片")
            time.sleep(0.5)

        return self.image_count

    def save_to_excel(self):
        """将图片信息保存到Excel"""
        if not self.image_data:
            print("   警告: 没有图片数据可保存到Excel")
            return None

        try:
            # 创建DataFrame，只包含绝对路径
            df = pd.DataFrame({
                'absolute_path': self.image_data
            })

            excel_filename = "test.xlsx"
            excel_path = os.path.join(os.getcwd(), excel_filename)

            # 保存Excel文件
            df.to_excel(excel_path, index=False)
            print(f"   Excel文件已保存: {excel_path}")
            return os.path.abspath(excel_path)

        except Exception as e:
            print(f"   保存Excel失败: {e}")
            return None

    def run(self):
        """运行爬虫"""
        print("=== 新浪军事图片爬虫 ===")
        start_time = time.time()

        image_count = self.crawl_images()
        print(f"爬取完成，开始保存Excel...")
        excel_path = self.save_to_excel()

        end_time = time.time()
        elapsed_time = end_time - start_time

        print(f"\n爬取完成!")
        print(f"   耗时: {elapsed_time:.1f}秒")
        print(f"   成功下载: {image_count}张图片")
        print(f"   保存路径: {os.path.abspath(self.images_folder)}")

        if excel_path:
            print(f"   Excel记录: {excel_path}")
        else:
            print(f"   Excel文件生成失败")

        return {
            'success': image_count > 0,
            'image_count': image_count,
            'excel_path': excel_path,
            'image_folder': os.path.abspath(self.images_folder)
        }


def main():
    """主函数"""
    crawler = SinaMilitaryImageCrawler()
    result = crawler.run()

    if result['success']:
        print(f"\n成功下载 {result['image_count']} 张图片")
        print(f"图片保存在: {result['image_folder']}")
        if result['excel_path']:
            print(f"Excel记录: {result['excel_path']}")
    else:
        print(f"\n爬取失败")


if __name__ == "__main__":
    main()