import sys
sys.path.append('.')
from src.generation.citation_parser import validate_answer_grounding

sources = [
    {
        'source_id': 1, 'title': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)', 'language': 'en', 'category': 'devices', 'record_type': 'product',
        'final_score': 8.1875, 'citation_url': 'https://te.eg/web/guest/w/ac1300-whole-home-mesh-wi-fi-system-pack-of-1-',
        'content': 'Product: AC1300 Whole Home Mesh Wi-Fi System (Pack of 1) Category: Routers Brand: TP-Link Model: TP-Link Wi-Fi Mesh Deco M5 Price: 3,100 EGP Price includes VAT: Unknown Warranty: 1 Year warranty applying terms and conditions Specifications: * LAN Interface: 1x10/100/1000 Mbps Ethernet RJ-45 Port * Operation Modes: .Wireless Router mode and Access point mode * WAN Interface: 1x10/100/1000 Mbps Ethernet RJ-45 Port * WLAN Feature: Dual-Band 802.11@2.4GHZ b/g/n up to 400 Mbps, 8',
        'metadata': {'product_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)', 'package_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)', 'search_aliases': []}
    },
    {
        'source_id': 2, 'title': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3)', 'language': 'en', 'category': 'devices', 'record_type': 'product',
        'final_score': 8.0, 'citation_url': 'https://te.eg/web/guest/w/ac1300-whole-home-mesh-wi-fi-system-pack-of-3-',
        'content': 'Product: AC1300 Whole Home Mesh Wi-Fi System (Pack of 3) Category: Routers Brand: TP-Link Model: TP-Link Wi-Fi Mesh Deco M5 Price: 7,777 EGP Price includes VAT: Unknown Warranty: 1 Year warranty applying terms and conditions Specifications: * LAN Interface: 2x10/100/1000 Mbps Ethernet RJ-45 Port',
        'metadata': {'product_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3)', 'package_name': 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3)', 'search_aliases': []}
    }
]

query = 'Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 1'
answer = 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3) is a TP-Link device; router; model TP-Link Wi-Fi Mesh Deco M5 priced at 7,777 EGP. It includes a 1-year warranty and features LAN Interface: ... High quality of service (QoS) over Wi-Fi.. [2]'

val = validate_answer_grounding(answer, sources, query=query)
print("With Citation [2]:", val)

answer = 'AC1300 Whole Home Mesh Wi-Fi System (Pack of 3) is a TP-Link device; router; model TP-Link Wi-Fi Mesh Deco M5 priced at 7,777 EGP. It includes a 1-year warranty and features LAN Interface: ... High quality of service (QoS) over Wi-Fi.. [1]'

val = validate_answer_grounding(answer, sources, query=query)
print("With Citation [1]:", val)
