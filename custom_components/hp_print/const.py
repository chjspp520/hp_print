"""Constants for HP Printer Monitor integration."""

DOMAIN = "hp_print"

# Config keys
CONF_HOST = "host"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DAYLIST_DAYS = "daylist_days"

# Defaults
DEFAULT_NAME = "HP Printer"
DEFAULT_SCAN_INTERVAL = 60  # seconds
DEFAULT_DAYLIST_DAYS = 90   # days to retain in daylist

# Storage
STORAGE_VERSION = 1
STORAGE_KEY = "hp_print.period_usage"

# Period usage sensor data keys (absolute cumulative from coordinator)
PERIOD_KEYS = [
    "print", "scan", "copy", "fax", "jam_printer",
    "ink_black", "ink_cyan", "ink_magenta", "ink_yellow",
]
PERIOD_SOURCE_MAP = {
    "print": "print_app_total_pages",
    "scan": "scan_total_images",
    "copy": "copy_total_pages",
    "fax": "fax_total_pages",
    "jam_printer": "print_jam_count",
    "ink_black": "ink_black_level_remaining",
    "ink_cyan": "ink_cyan_level_remaining",
    "ink_magenta": "ink_magenta_level_remaining",
    "ink_yellow": "ink_yellow_level_remaining",
}

# Ink colors for the "lik" attribute
INK_COLOR_KEYS = ["black", "cyan", "magenta", "yellow"]

# Suffixes for period entry values (unit display)
PERIOD_UNIT_MAP = {
    "ink_black": "%",
    "ink_cyan": "%",
    "ink_magenta": "%",
    "ink_yellow": "%",
}

# XML paths
XML_URL_PATH = "/DevMgmt/ProductUsageDyn.xml"
XML_LOGS_URL_PATH = "/DevMgmt/ProductLogsDyn.xml"

# SNMP OIDs
SNMP_PORT = 161
SNMP_COMMUNITY = "public"
SNMP_OID_DEVICE_STATUS = "1.3.6.1.2.1.25.3.2.1.5.1"
SNMP_OID_PRINTER_STATUS = "1.3.6.1.2.1.25.3.5.1.1.1"
SNMP_OID_ERROR_STATE = "1.3.6.1.2.1.25.3.5.1.2.1"

# SNMP status → human-readable mapping
DEVICE_STATUS_MAP = {1: "其他", 2: "运行中", 3: "警告", 4: "测试中", 5: "停机"}
PRINTER_STATUS_MAP = {1: "其他", 2: "未知", 3: "空闲", 4: "打印中", 5: "预热中"}

# ----------------------------------------------------------------
# Sensor definitions: each sensor key maps to xml_tag, optional peid,
# plus a cn_name and unit.
# ----------------------------------------------------------------
# Printer engine sensors
PRINTER_SENSORS = {
    "engine_total_pages": {
        "tag": "TotalImpressions", "peid": 5082,
        "name": "引擎页面总数", "unit": "页", "icon": "mdi:printer",
        "subunit": "PrinterSubunit",
    },
    "mono_pages": {
        "tag": "MonochromeImpressions", "peid": None,
        "name": "黑白打印页数", "unit": "页", "icon": "mdi:printer",
        "subunit": "PrinterSubunit",
    },
    "color_pages": {
        "tag": "ColorImpressions", "peid": None,
        "name": "彩色打印页数", "unit": "页", "icon": "mdi:palette",
        "subunit": "PrinterSubunit",
    },
    "simplex_pages": {
        "tag": "SimplexSheets", "peid": None,
        "name": "单面打印页数", "unit": "页", "icon": "mdi:file-document",
        "subunit": "PrinterSubunit",
    },
    "duplex_pages": {
        "tag": "TotalImpressions", "peid": 5088,
        "name": "双面打印页数", "unit": "页", "icon": "mdi:file-document-multiple",
        "subunit": "PrinterSubunit",
    },
    "print_jam_count": {
        "tag": "JamEvents", "peid": 16076,
        "name": "打印卡纸次数", "unit": "次", "icon": "mdi:alert-circle",
        "subunit": "PrinterSubunit",
    },
    "print_mispick_count": {
        "tag": "MispickEvents", "peid": None,
        "name": "打印拾纸错误次数", "unit": "次", "icon": "mdi:alert",
        "subunit": "PrinterSubunit",
    },
    "ews_access_count": {
        "tag": "EWSAccessCount", "peid": 16081,
        "name": "EWS 访问次数", "unit": "次", "icon": "mdi:web",
        "subunit": "PrinterSubunit",
    },
    "network_impressions": {
        "tag": "NetworkImpressions", "peid": 25000,
        "name": "网络打印页数", "unit": "页", "icon": "mdi:lan",
        "subunit": "PrinterSubunit",
    },
    "wireless_impressions": {
        "tag": "WirelessNetworkImpressions", "peid": 25002,
        "name": "无线打印页数", "unit": "页", "icon": "mdi:wifi",
        "subunit": "PrinterSubunit",
    },
}

# Scanner sensors
SCANNER_SENSORS = {
    "adf_scan_pages": {
        "tag": "AdfImages", "peid": 6011,
        "name": "ADF 扫描页数", "unit": "页", "icon": "mdi:scanner",
        "subunit": "ScannerEngineSubunit",
    },
    "flatbed_scan_pages": {
        "tag": "FlatbedImages", "peid": None,
        "name": "平台扫描页数", "unit": "页", "icon": "mdi:scanner",
        "subunit": "ScannerEngineSubunit",
    },
    "scan_jam_count": {
        "tag": "JamEvents", "peid": None,
        "name": "扫描卡纸次数", "unit": "次", "icon": "mdi:alert-circle",
        "subunit": "ScannerEngineSubunit",
    },
    "scan_mispick_count": {
        "tag": "MispickEvents", "peid": None,
        "name": "扫描拾纸错误次数", "unit": "次", "icon": "mdi:alert",
        "subunit": "ScannerEngineSubunit",
    },
    "scan_total_images": {
        "tag": "ScanImages", "peid": 6000,
        "name": "总扫描图像数", "unit": "张", "icon": "mdi:image-multiple",
        "subunit": "ScannerEngineSubunit",
    },
}

# Copy sensors
COPY_SENSORS = {
    "copy_total_pages": {
        "tag": "TotalImpressions", "peid": 3019,
        "name": "总复印页数", "unit": "页", "icon": "mdi:content-copy",
        "subunit": "CopyApplicationSubunit",
    },
    "copy_color_pages": {
        "tag": "ColorImpressions", "peid": None,
        "name": "彩色复印页数", "unit": "页", "icon": "mdi:content-copy",
        "subunit": "CopyApplicationSubunit",
    },
    "copy_mono_pages": {
        "tag": "MonochromeImpressions", "peid": None,
        "name": "黑白复印页数", "unit": "页", "icon": "mdi:content-copy",
        "subunit": "CopyApplicationSubunit",
    },
}

# Fax sensors
FAX_SENSORS = {
    "fax_total_pages": {
        "tag": "TotalImpressions", "peid": 4016,
        "name": "总传真页数", "unit": "页", "icon": "mdi:fax",
        "subunit": "FaxApplicationSubunit",
    },
    "fax_color_pages": {
        "tag": "ColorImpressions", "peid": None,
        "name": "彩色传真页数", "unit": "页", "icon": "mdi:fax",
        "subunit": "FaxApplicationSubunit",
    },
    "fax_mono_pages": {
        "tag": "MonochromeImpressions", "peid": None,
        "name": "黑白传真页数", "unit": "页", "icon": "mdi:fax",
        "subunit": "FaxApplicationSubunit",
    },
}

# Print application sensors
PRINT_APP_SENSORS = {
    "print_app_total_pages": {
        "tag": "TotalImpressions", "peid": 7009,
        "name": "打印应用总页数", "unit": "页", "icon": "mdi:application",
        "subunit": "PrintApplicationSubunit",
    },
    "print_app_photo_pages": {
        "tag": "PhotoImpressions", "peid": 7002,
        "name": "照片打印页数", "unit": "页", "icon": "mdi:image",
        "subunit": "PrintApplicationSubunit",
    },
}

# Ink/consumable sensor keys per color station
INK_COLORS = {
    1: "Cyan",
    2: "Magenta",
    3: "Yellow",
    4: "Black",
}

# ----------------------------------------------------------------
# All subunit-level sensors combined for easy iteration
# ----------------------------------------------------------------
ALL_SUBUNIT_SENSORS = {}
ALL_SUBUNIT_SENSORS.update(PRINTER_SENSORS)
ALL_SUBUNIT_SENSORS.update(SCANNER_SENSORS)
ALL_SUBUNIT_SENSORS.update(COPY_SENSORS)
ALL_SUBUNIT_SENSORS.update(FAX_SENSORS)
ALL_SUBUNIT_SENSORS.update(PRINT_APP_SENSORS)

# ----------------------------------------------------------------
# Event code → Chinese description lookup (from printer EWS)
# ----------------------------------------------------------------
EVENT_CODE_MAP: dict[str, str] = {
    "15.00.00": "未知卡纸",
    "17.00.00": "Black 墨盒故障",
    "17.00.60": "Black 墨盒墨水量偏低",
    "17.00.80": "Black 墨盒为空",
    "17.01.60": "Cyan 墨盒墨水量偏低",
    "17.01.80": "Cyan 墨盒为空",
    "17.02.00": "Magenta 墨盒故障",
    "17.02.60": "Magenta 墨盒墨水量偏低",
    "17.02.80": "Magenta 墨盒为空",
    "17.03.60": "Yellow 墨盒墨水量偏低",
    "17.03.80": "Yellow 墨盒为空",
    "17.99.40": "已安装原装 HP 耗材",
    "41.03.01": "与纸盒 1 大小不匹配",
    "41.03.02": "与纸盒 2 大小不匹配",
}
