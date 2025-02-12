from io import StringIO
import time
import logging
from zoneinfo import ZoneInfo

from services.notification import serverchan, send_email, feishu_webhook, wecom_app
from services.utils.config_parser import config
from services.utils.serial_manager import SerialManager
from .utils.sms import parse_pdu, encode_pdu
from .utils.commands import at_commands

logger = logging.getLogger("PyAirLink")


def web_send_at_command(command, keywords=None, timeout=3):
    with SerialManager() as serial_manager:
        response = serial_manager.send_at_command(command, keywords=keywords, timeout=timeout)
        return response


def initialize_module():
    """
    初始化模块
    """
    logger.info("正在初始化模块...")

    # 发送基本AT指令
    with SerialManager() as serial_manager:
        response = serial_manager.send_at_command(at_commands.at(), keywords="OK")
        if not response:
            logger.error("无法与模块通信")
            return False

        response = serial_manager.send_at_command(at_commands.cpin(), keywords="OK")
        if "READY" not in response:
            logger.error("未检测到 SIM 卡，请检查后重启模块")
            return False
        logger.info("SIM 卡已就绪")

        response = serial_manager.send_at_command(at_commands.cmgf(), keywords="OK")
        if not response:
            logger.error("无法设置短信格式为 PDU")
            return False
        logger.info("短信格式设置为 PDU")

        response = serial_manager.send_at_command(at_commands.cscs(), keywords="OK")
        if not response:
            logger.error("无法设置字符集为 UCS2")
            return False
        logger.info("字符集设置为 UCS2")

        response = serial_manager.send_at_command(at_commands.cpms(), keywords="OK")
        if not response:
            logger.error("无法配置新短信暂存区")
            return False
        logger.info("新短信暂存区配置完成")

        response = serial_manager.send_at_command(at_commands.cnmi(), keywords="OK")
        if not response:
            logger.error("无法配置新短信通知")
            return False
        logger.info("新短信通知配置完成")

        # 检查 GPRS 附着状态
        while True:
            response = serial_manager.send_at_command(at_commands.cgatt(), keywords="+CGATT: 1")
            if response:
                logger.info("GPRS 已附着")
                break
            else:
                logger.warning("GPRS 未附着，5秒后重试...")
                time.sleep(5)

    logger.info("模块初始化完成")
    return True


def web_restart():
    with SerialManager() as serial_manager:
        resp = serial_manager.send_at_command(at_commands.reset())
        if not resp:
            logger.warning("模块重启不成功")
        else:
            logger.info("模块重启成功")
    time.sleep(3)
    return initialize_module()


def handle_sms(phone_number, sms_content, receive_time, tz="Asia/Shanghai"):
    """
    处理接收到的短信
    """
    logger.info(f"在{receive_time}收到短信来自 {phone_number}，内容: {sms_content}")
    channels = {'serverchan': serverchan,'mail': send_email, 'feishu_webhook': feishu_webhook, "wecom_app": wecom_app}
    use_channels = config.notification()
    if use_channels:
        title = f'收到来自 {phone_number} 的短信'
        content = f'时间: {receive_time.astimezone(ZoneInfo(tz))},\n内容: {sms_content}'
        for channel in use_channels:
            func = channels[channel]
            try:
                func(title, content)
            except Exception as e:
                logger.error(f'短信推送错误，渠道类型： {channel}， 错误： {e}')
    return True


def send_sms(to, text):
    """
    使用AT指令在PDU模式下发送SMS。
    ser是已打开的pyserial串口对象。
    to为目标号码字符串（如"+8613800138000"），text为短信内容（UTF-8字符串）。
    """
    logging_tag = "send_sms"
    pdu, length = encode_pdu(to, text)
    if not pdu or not length:
        logger.error("%s: 短信编码失败", logging_tag)
        return False

    # 设置CMGF=0进入PDU模式（如果之前没设置过）
    with SerialManager() as serial_manager:
        resp = serial_manager.send_at_command(at_commands.cmgf())
        if not resp:
            logger.error("%s: 无法进入PDU模式", logging_tag)
            return False

        # 发送AT+CMGS指令
        resp = serial_manager.send_at_command(at_commands.cmgs(length), keywords='>', timeout=3)
        if not resp:
            logger.error("%s: 未收到短信发送提示符 '>'，超时", logging_tag)
            return False

        # 发送PDU数据和Ctrl+Z结束符(0x1A)
        resp = serial_manager.send_at_command(pdu.encode('utf-8') + b'\x1A', keywords='+CMGS:', timeout=5)
        logger.debug("%s: 已发送PDU数据，等待发送成功URC", logging_tag)
        if resp:
            logger.info("%s: 短信发送成功", logging_tag)
            return True
        else:
            logger.error("%s: 未收到+CMGS:确认，发送失败", logging_tag)
            return False


def sms_listener(stop_event):
    """
    定期查询是否有新短信的监听器
    """
    with SerialManager() as serial_manager:
        while not stop_event.is_set():
            try:
                # 发送AT+CMGL命令查询未读短信
                response = serial_manager.send_at_command(at_commands.cmgl(stat=0), keywords=['OK'])
                # logger.warning(f"本次查询短信收到回复: {response}")
                if response and '+CMGL:' in response:
                    lines = response.strip().splitlines()
                    i = 0
                    massages = []
                    while i < len(lines):
                        line = lines[i].strip()
                        if line.startswith('+CMGL:'):
                            # 当前行为短信头，下一行应为 PDU 数据
                            if i + 1 < len(lines):
                                pdu_line = lines[i + 1].strip()
                                # 解析短信通知
                                try:
                                    match = parse_pdu(StringIO(pdu_line))
                                    if isinstance(match, dict):
                                        massages.append(match)
                                    else:
                                        logger.warning(f"对PDU: {pdu_line} 的解析不正确")
                                except Exception as e:
                                    logger.error(f"对PDU: {pdu_line} 的解析出错 {e}")
                                i += 2  # 跳过 PDU 数据行，继续处理下一条短信
                            else:
                                # 错误处理：+CMGL 行后没有 PDU 数据
                                logger.warning(f"在索引 {i} 处，+CMGL 行后缺少 PDU 数据")
                                i += 1
                        else:
                            i += 1
                    for massage in massages:
                        phone_number = massage.get('sender').get('number')
                        receive_time = massage.get('scts')
                        sms_content = massage.get('user_data').get('data')
                        handle_sms(phone_number, sms_content, receive_time)
                    serial_manager.send_at_command(at_commands.cmgd(), keywords=['OK'])
                # 短暂休眠，避免占用过多资源
                time.sleep(1)
            except Exception as e:
                logger.error(f"sms_listener 出错: {e}")
                time.sleep(1)


if __name__ == "__main__":
    pass
