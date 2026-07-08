import sys
sys.path.append('.')
from src.generation.answer_generator import AnswerGenerator

ag = AnswerGenerator()
sources = [
    {
        'chunk_id': '1', 'title': 'نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 1)', 'language': 'mixed', 'category': 'devices', 'record_type': 'product',
        'final_score': 9.1875, 'citation_url': 'https://te.eg/web/guest/w/ac1300-whole-home-mesh-wi-fi-system-pack-of-1-',
        'content': 'Product: نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 1) Category: Routers Brand: TP-Link Model: TP-Link Wi-Fi Mesh Deco M5 Price: 3,100 EGP Price includes VAT: Unknown Warranty: 1 Year warranty applying terms and conditions Specifications: * LAN Interface: 1x10/100/1000 Mbps Ethernet RJ-45 Port * Operation Modes: .Wireless Router mode and Access point mode * WAN Interface: 1x10/100/1000 Mbps Ethernet RJ-45 Port * WLAN Feature: Dual-Band 802.11@2.4GHZ b/g/n up to 400 Mbps, 8',
        'metadata': {'product_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)', 'package_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)'}
    }
]
query = 'Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 1'
print(ag.build_conservative_answer(query, sources, 'en'))
