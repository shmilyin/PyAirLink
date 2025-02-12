import logging
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import json
import time
import hmac
import hashlib
import base64

from .utils.config_parser import config

logger = logging.getLogger("PyAirLink")


def serverchan(title, desp='', options=None):
    """
    照抄自 https://github.com/easychen/serverchan-demo
    """
    sendkey = config.server_chan()
    options = options if options else {}
    # 判断 sendkey 是否以 'sctp' 开头，并提取数字构造 URL
    if sendkey.startswith('sctp'):
        match = re.match(r'sctp(\d+)t', sendkey)
        if match:
            num = match.group(1)
            url = f'https://{num}.push.ft07.com/send/{sendkey}.send'
        else:
            raise ValueError('Invalid sendkey format for sctp')
    else:
        url = f'https://sctapi.ftqq.com/{sendkey}.send'
    data = {
        'title': title,
        'desp': desp,
        **options
    }
    try:
        response = requests.post(url, json=data)
        if response.ok:
            logger.info(f"serverChan 已推送，返回： {response.json()}")
            return True
        else:
            logger.warning(f"serverChan 推送失败，返回： {response.json()}")
    except Exception as e:
        logger.error(f"serverChan推送出错: {e}")
    return False

def feishu_webhook(title, desp='', options=None):
    feishu_webhook_config = config.feishu_webhook()
    webhook_url = feishu_webhook_config.get("webhook_url")
    secret = feishu_webhook_config.get("secret")

    # 检查必要参数
    if not webhook_url:
        logger.warning("飞书群聊机器人webhook_url未填写，跳过调用")
        return
    if not secret:
        logger.warning("飞书群聊机器人secret未填写，跳过调用")
        return

    try:
        timestamp = str(int(time.time()))
        string_to_sign = '{}\n{}'.format(timestamp, secret)
        hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')

        # 构造请求体
        request_body = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "text",
            "content": {
                "text": f"{title}\n{desp}"
            }
        }

        logger.info("正在发送飞书群聊机器人通知")

        # 发送请求
        response = requests.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            json=request_body,
            # 如需禁用IPv6可添加适配器配置（此处略）
        )

        # 处理响应
        if response.status_code != 200:
            logger.warning(f"发送失败，状态码：{response.status_code}，响应：{response.text}")
            return

        resp = response.json()
        if resp.get("code") != 0:
            logger.warning(f"飞书返回错误：{resp.get('code')} - {resp.get('msg', '未知错误')}")
        else:
            logger.info("飞书群聊机器人发送成功")

    except Exception as e:
        logger.error(f"飞书群聊机器人发送失败: {str(e)}")

def wecom_app(title, desp='', options=None):
    wecom_app_config = config.wecom_app()

    try:
        url = wecom_app_config.get("url")
        corpid = wecom_app_config.get("corpid")
        corpsecret = wecom_app_config.get("corpsecret")
        agentid = wecom_app_config.get("agentid")
        touser = wecom_app_config.get("touser")

        # 检查必要参数
        if not url:
            logger.warning("企业微信APP推送 url 未填写，跳过调用")
            return
        if not corpid:
            logger.warning("企业微信APP推送 corpid 未填写，跳过调用")
            return
        if not corpsecret :
            logger.warning("企业微信APP推送 corpsecret 未填写，跳过调用")
            return
        if not agentid :
            logger.warning("企业微信APP推送 agentid 未填写，跳过调用")
            return
        if not touser :
            logger.warning("企业微信APP推送 touser 未填写，跳过调用")
            return

        logger.info("正在获取企业微信APP推送TOKEN")
        get_token_url = '{}/cgi-bin/gettoken?corpid={}&corpsecret={}'.format(url, corpid, corpsecret)
        # 发送请求
        response = requests.get(get_token_url)

        # 处理响应
        if response.status_code != 200:
            logger.error(f"企业微信APP推送，获取TOKEN失败，状态码：{response.status_code}，响应：{response.text}")
            return

        resp = response.json()
        if resp.get("errcode") != 0:
            logger.error(f"企业微信APP推送，获取TOKEN失败，返回错误：{resp.get('errcode')} - {resp.get('errmsg', '未知错误')}")

        access_token = resp.get("access_token")

        if not access_token :
            logger.error("企业微信APP发送消息失败 access_token is nil")
            return
        logger.info(f"正在发送企业微信APP通知，已获取TOKEN：{access_token}")
        send_url = '{}/cgi-bin/message/send?debug=1&access_token={}'.format(url, access_token)

        # 构造请求体
        request_body = {
            "touser": touser,
            "msgtype": "text",
            "agentid": agentid,
            "text": {
                "content": f"{title}\n{desp}"
            },
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 0,
            "duplicate_check_interval": 1800
        }

        logger.info(f"send_url:{send_url}")
        logger.info("正在发送企业微信APP通知")

        # 发送请求
        response = requests.post(
            send_url,
            headers={"Content-Type": "application/json"},
            json=request_body,
        )

        # 处理响应
        if response.status_code != 200:
            logger.warning(f"企业微信APP发送失败，状态码：{response.status_code}，响应：{response.text}")
            return

        resp = response.json()
        if resp.get("errcode") != 0:
            logger.warning(f"企业微信APP返回错误：{resp.get('errcode')} - {resp.get('errmsg', '未知错误')}")
        else:
            logger.info("企业微信APP发送成功")

    except Exception as e:
        logger.error(f"企业微信APP发送失败: {str(e)}")

def send_email(subject, body):
    email_account = config.mail()
    try:
        # 创建邮件内容
        msg = MIMEMultipart()
        msg['From'] = email_account.get('account')
        msg['To'] = email_account.get('mail_to')
        msg['Subject'] = subject

        # 邮件正文内容
        msg.attach(MIMEText(body, 'plain'))

        # 创建 SMTP 会话
        server = smtplib.SMTP(email_account.get('smtp_server'), email_account.get('smtp_port'), timeout=5)

        if email_account.get('tls'):
            server.starttls()  # 启用 TLS 加密

        # 登录到 SMTP 服务器
        server.login(email_account.get('account'), email_account.get('password'))

        # 发送邮件
        server.sendmail(email_account.get('account'), email_account.get('mail_to'), msg.as_string())

        # 退出 SMTP 会话
        server.quit()

        logger.info(f"邮件发送成功到 {email_account.get('mail_to')}")
    except Exception as e:
        logger.error(f"邮件发送失败: {str(e)}")