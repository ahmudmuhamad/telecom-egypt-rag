import sys
sys.path.append('.')
from src.retrieval.source_formatter import prefer_generation_sources, deduplicate_sources

results = [
    {
        'chunk_id': '1', 'title': 'نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 1)', 'language': 'mixed', 'category': 'devices', 'record_type': 'product',
        'final_score': 9.1875, 'citation_url': 'https://te.eg/web/guest/w/ac1300-whole-home-mesh-wi-fi-system-pack-of-1-',
        'content': 'Product: نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 1) Category: Routers Brand: TP-Link Model: TP-Link Wi-Fi Mesh Deco M5 Price: 3,100 EGP Price includes VAT: Unknown Warranty: 1 Year warranty applying terms and conditions Specifications: * LAN Interface: 1x10/100/1000 Mbps Ethernet RJ-45 Port * Operation Modes: .Wireless Router mode and Access point mode * WAN Interface: 1x10/100/1000 Mbps Ethernet RJ-45 Port * WLAN Feature: Dual-Band 802.11@2.4GHZ b/g/n up to 400 Mbps, 8',
        'metadata': {'product_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)', 'package_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)'}
    },
    {
        'chunk_id': '2', 'title': 'نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 3)', 'language': 'mixed', 'category': 'devices', 'record_type': 'product',
        'final_score': 8.8125, 'citation_url': 'https://te.eg/web/guest/w/ac1300-whole-home-mesh-wi-fi-system-pack-of-3-',
        'content': 'Product: نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 3) Category: Routers Brand: TP-Link Model: TP-Link Wi-Fi Mesh Deco M5 Price: 7,777 EGP Price includes VAT: Unknown Warranty: 1 Year warranty applying terms and conditions Specifications: * LAN Interface: 2x10/100/1000 Mbps Ethernet RJ-45 Port',
        'metadata': {'product_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3)', 'package_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3)'}
    },
    {
        'chunk_id': '3', 'title': 'نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 2)', 'language': 'mixed', 'category': 'devices', 'record_type': 'product',
        'final_score': 8.4375, 'citation_url': 'https://te.eg/web/guest/w/ac1300-whole-home-mesh-wi-fi-system-pack-of-2-',
        'content': 'Product: نظام شبكة الواي فاي المتكامل للمنزل بتكنولوجيا AC1300 (Pack of 2)',
        'metadata': {'product_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 2)'}
    },
]

query = 'Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 1'
out = prefer_generation_sources(results, query)
print("After sorting:")
for idx, r in enumerate(out):
    title = r['title'].encode('ascii', 'ignore').decode()
    print(f"{idx+1}. {title} (Score: {r['final_score']})")
