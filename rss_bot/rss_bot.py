""" This is a bot that fetches articles from RSS feeds and send a report by
    email

    @author: Guillaume Martin
"""
import os
import xml.etree.ElementTree as et
from datetime import date, timedelta
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import feedparser
import dateutil.parser as parser
import boto3
from botocore.exceptions import ClientError


# Load environment variables
try:
    # Try to get the values from the system's environment variable
    # Mostly in production
    SMTP_SERVER = os.getenv("SMTP_SERVER", None)
    SMTP_PORT = os.getenv("SMTP_PORT", 587)
    SMTP_USER = os.getenv("SMTP_USER", None)
    SMTP_PWD = os.getenv("SMTP_PWD", None)
    FROM_EMAIL = os.getenv("FROM_EMAIL", None)
    TO_EMAIL = os.getenv("TO_EMAIL", None)
except Exception:
    print("Failed to load environment variables.")


class SmtpMailer:

    def __init__(self, smtp_server, smtp_port, smtp_user, smtp_pwd):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_pwd = smtp_pwd
        self.context = ssl.create_default_context()

    def _set_message(self, from_email, to_email,
                     subject, message, type="text"):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        content = MIMEText(message, type)
        msg.attach(content)

        self.message = msg.as_string()

    def send_email(self, from_email, to_email,
                   subject=None, content=None, type="text"):
        self._set_message(from_email, to_email, subject, content, type)

        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            try:
                server.starttls(context=self.context)
                server.login(self.smtp_user, self.smtp_pwd)
                server.sendmail(from_email, to_email, self.message)
                response = {"status_code": 201, "details": "email sent"}
            except Exception as e:
                response = {"status_code": 400, "details": e}

        return response


def timer(func):
    """Shows the execution time if a function"""
    def wrap_func(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        print(f"{func.__name__!r} executed in {(end_time-start_time):.4f}s")
        return result
    return wrap_func


def load_feeds():
    """ Loads the content of the opml file into an xml tree object
    """
    aws_bucket = os.getenv("AWS_BUCKET")
    feedlist_file = os.getenv("FEEDLIST_FILE")
    try:
        s3 = boto3.client("s3")
        response = s3.get_object(Bucket=aws_bucket, Key=feedlist_file)
    except ClientError as e:
        print(f"Failed to load the the feeds list: {e}")
        return None

    feeds = response["Body"].read()
    tree = et.fromstring(feeds)

    return tree


def published_date(entry: dict):
    """ Attempts to extract the article's publication date from the rss entry
        data

    Parameters
    ----------
    entry: dict
        A RSS entry data

    Returns
    -------
    datetime
        The article's publication time as a datetime object.
    """
    date_keys = [
        "published_parsed",
        "updated_parsed",
        "pubDate",
        "updated",
        "published",
    ]

    for k in date_keys:
        try:
            pub_date = entry[k]
            dt = parser.parse(pub_date)
            return dt
        except Exception:
            continue

    return None


@timer
def get_articles(feed_url: str) -> str:
    """ Extracts all the articles from a RSS feed's URL and generates a HTML
        unordered list with the title and a link to the article.

    Parameters
    ----------
    feed_url: String
        The URL of the RSS feed.

    Returns
    -------
    String

    """
    articles = "<ul>"

    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        print(f"Failed to fetch feed content: {e}")
        return None

    if feed.get("status") == 404:
        return "Not Found"

    entries = feed["entries"]
    articles_count = 0
    for entry in entries:
        title = entry["title"]
        article_url = entry["link"]
        pub_date = published_date(entry)
        yesterday = date.today() - timedelta(days=1)
        if pub_date.date() == yesterday:
            articles += f"<li><a href='{article_url}'>{title}</a></li>"
            articles_count += 1

    articles += "</ul>"
    print(f"found {articles_count} articles")
    if articles_count > 0:
        return articles
    else:
        return None


def process_outline(outline):

    outline_type = outline.attrib.get("type")
    title = outline.attrib.get("title")
    url = outline.attrib.get("xmlUrl")

    # Get category's name
    # TODO Only show category if there are articles
    if outline_type == "folder":
        print(f"==========  {title}  ==========")
        return f"<hr><h1>{title}</h1>"

    # Get source's name
    print(f"----------  {title}  ----------")
    blog = f"<h2>{title}</h2>"

    # Get new articles
    articles = get_articles(url)

    if articles == "Not found":
        return "Not Found"
    elif articles is not None:
        return blog + articles
    else:
        return None


def main():

    # Load feeds
    tree = load_feeds()
    assert tree is not None, "Failed to load the RSS feeds."

    nodes = tree.findall(".//outline")

    report = ""
    errors = "<hr><h1>Errors</h1>"

    # Fetch new articles
    for outline in nodes:
        # Get the previous day's articles from the feed into an HTML list.
        blog_articles = process_outline(outline)

        if blog_articles == "Not found":
            title = outline.attrib.get("title")
            url = outline.attrib.get("xmlUrl")
            errors += f"<a src='{url}'>{title}</a>"
            continue
        elif blog_articles is not None:
            report += blog_articles
        else:
            continue

    report += errors

    # Send email
    subject = "Today's new articles and videos."
    smtp = SmtpMailer(SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PWD)
    smtp.send_email(FROM_EMAIL, TO_EMAIL, subject, report, "html")


def lambda_handler(event, context):
    main()
