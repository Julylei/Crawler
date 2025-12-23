import requests
import os
import pandas as pd
import time
import json
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup


class PhoenixNewsImageCrawler:
    def __init__(self, save_dir="test"):  # 改为test
        self.base_url = "https://mil.ifeng.com/shanklist/originalcard/14-35081-"
        self.save_dir = save_dir
        self.excel_file = "test.xlsx"  # 改为test.xlsx
        self.image_data = []
        self.image_counter = 1  # 图片计数器

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

    def get_page_content(self, url):
        """获取页面内容"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        }

        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.encoding = 'utf-8'
            return response.text
        except Exception as e:
            print(f"请求页面失败: {e}")
            return None

    def get_article_urls(self):
        """从列表页获取所有文章的URL"""
        print("正在获取文章列表...")
        html_content = self.get_page_content(self.base_url)
        if not html_content:
            return []

        # 从JavaScript变量中提取文章URL
        pattern = r'var allData = ({.*?});'
        match = re.search(pattern, html_content, re.DOTALL)

        article_urls = []
        if match:
            try:
                json_str = match.group(1)
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)

                all_data = json.loads(json_str)
                newsstream = all_data.get('newsstream', [])

                for item in newsstream:
                    if 'url' in item and item['url']:
                        article_urls.append({
                            'url': item['url'],
                            'title': item.get('title', ''),
                            'news_time': item.get('newsTime', '')
                        })

                print(f"找到 {len(article_urls)} 篇文章")

            except json.JSONDecodeError as e:
                print(f"JSON解析错误: {e}")

        return article_urls

    def extract_images_from_article(self, html_content, article_info):
        """从文章页面提取图片"""
        images = []

        # 方法1: 从allData.slideData中提取（文章详情页的图片数据）
        pattern = r'var allData = ({.*?});'
        match = re.search(pattern, html_content, re.DOTALL)

        if match:
            try:
                json_str = match.group(1)
                json_str = re.sub(r',\s*}', '}', json_str)
                json_str = re.sub(r',\s*]', ']', json_str)

                all_data = json.loads(json_str)

                # 提取slideData中的图片
                if 'slideData' in all_data:
                    for i, slide in enumerate(all_data['slideData']):
                        if slide.get('type') == 'pic' and slide.get('url'):
                            images.append({
                                'url': slide['url'],
                                'description': slide.get('description', ''),
                                'width': slide.get('width', ''),
                                'height': slide.get('height', ''),
                                'index': i + 1,
                                'filename': os.path.basename(urlparse(slide['url']).path)
                            })

                print(f"从slideData中找到 {len(images)} 张图片")

            except json.JSONDecodeError as e:
                print(f"文章JSON解析错误: {e}")

        # 方法2: 从img标签中提取高清图片
        if not images:
            soup = BeautifulSoup(html_content, 'html.parser')
            img_tags = soup.find_all('img')

            for img in img_tags:
                src = img.get('src') or img.get('data-src')
                if src and 'ucms' in src and 'http' in src:
                    # 只提取ucms域的高清图片
                    images.append({
                        'url': src,
                        'description': img.get('alt', ''),
                        'filename': os.path.basename(urlparse(src).path),
                        'index': len(images) + 1
                    })

            print(f"从img标签中找到 {len(images)} 张图片")

        return images

    def download_image(self, img_info, article_info):
        """下载单张图片"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': article_info['url'],
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            }

            print(f"  下载第 {self.image_counter} 张图片")

            response = requests.get(img_info['url'], headers=headers, timeout=15)
            response.raise_for_status()

            # 按照数字命名：001.jpg, 002.jpg, 003.jpg...
            file_extension = os.path.splitext(img_info['filename'])[1]
            if not file_extension or len(file_extension) > 5:
                file_extension = '.jpg'

            # 关键修改：只使用数字命名，不使用文章标题
            filename = f"{self.image_counter:03d}{file_extension}"
            filepath = os.path.join(self.save_dir, filename)

            # 保存图片
            with open(filepath, 'wb') as f:
                f.write(response.content)

            file_info = {
                'image_number': self.image_counter,
                'article_title': article_info['title'],
                'article_url': article_info['url'],
                'news_time': article_info.get('news_time', ''),
                'image_url': img_info['url'],
                'local_path': os.path.abspath(filepath),
                'filename': filename,
                'description': img_info.get('description', ''),
                'width': img_info.get('width', ''),
                'height': img_info.get('height', ''),
                'download_time': time.strftime('%Y-%m-%d %H:%M:%S'),
                'file_size': os.path.getsize(filepath)
            }

            print(f"  ✓ 下载成功: {filename}")
            self.image_counter += 1  # 计数器增加

            return file_info

        except Exception as e:
            print(f"  ✗ 下载失败: {e}")
            return None

    def crawl_articles_images(self, max_images=100):
        """爬取多篇文章的图片，直到达到指定数量"""
        print("开始爬取凤凰军事新闻图片...")
        print(f"目标网址: {self.base_url}")
        print(f"目标图片数量: {max_images} 张")

        # 获取文章列表
        articles = self.get_article_urls()
        if not articles:
            print("未找到文章列表")
            return

        total_images = 0
        processed_articles = 0

        for i, article in enumerate(articles):
            # 如果已经达到目标图片数量，停止爬取
            if total_images >= max_images:
                print(f"\n已达到目标图片数量 {max_images} 张，停止爬取")
                break

            processed_articles += 1
            print(f"\n{'=' * 60}")
            print(f"处理第 {i + 1}/{len(articles)} 篇文章")
            print(f"标题: {article['title']}")
            print(f"URL: {article['url']}")
            print(f"当前已下载: {total_images}/{max_images} 张图片")
            print(f"{'=' * 60}")

            # 获取文章内容
            html_content = self.get_page_content(article['url'])
            if not html_content:
                print("无法获取文章内容，跳过")
                continue

            # 提取文章中的图片
            article_info = {
                'title': article['title'],
                'url': article['url'],
                'news_time': article.get('news_time', '')
            }

            images = self.extract_images_from_article(html_content, article_info)

            if not images:
                print("本文未找到图片")
                continue

            # 下载图片
            article_image_count = 0
            for img_info in images:
                # 如果已经达到目标图片数量，停止下载
                if total_images >= max_images:
                    break

                result = self.download_image(img_info, article_info)
                if result:
                    self.image_data.append(result)
                    article_image_count += 1
                    total_images += 1

                # 图片间延迟
                time.sleep(1)

            print(f"本文下载完成: {article_image_count} 张图片")

            # 文章间延迟
            if total_images < max_images and i < len(articles) - 1:
                print("等待2秒后处理下一篇文章...")
                time.sleep(2)

        # 保存到Excel
        self.save_to_excel()

        print(f"\n{'=' * 60}")
        print(f"爬取完成！")
        print(f"处理文章: {processed_articles}/{len(articles)} 篇")
        print(f"下载图片: {total_images} 张")
        print(f"图片保存到: {os.path.abspath(self.save_dir)}")
        print(f"路径数据保存到: {self.excel_file}")
        print(f"{'=' * 60}")

    def save_to_excel(self):
        """将图片路径保存到Excel - 只保存绝对路径"""
        if self.image_data:
            # 只提取绝对路径数据
            path_data = []
            for item in self.image_data:
                path_data.append({
                    'absolute_path': item['local_path']
                })

            # 创建DataFrame，只包含绝对路径
            df = pd.DataFrame(path_data)

            # 保存到Excel
            df.to_excel(self.excel_file, index=False)
            print(f"图片绝对路径已保存到: {self.excel_file}")

            # 打印所有图片路径
            print("\n所有图片绝对路径:")
            for item in path_data:
                print(f"{item['absolute_path']}")
        else:
            print("没有数据可保存")

    def get_image_paths(self):
        """获取所有图片路径"""
        return self.image_data


# 使用示例
if __name__ == "__main__":
    # 创建爬虫实例
    crawler = PhoenixNewsImageCrawler("test")  # 文件夹名称改为test

    # 爬取100张图片
    crawler.crawl_articles_images(max_images=100)