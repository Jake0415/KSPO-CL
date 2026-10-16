"""Initial crawl_source registry for sports.re.kr (from GNB, IA report §1).

priority: 1=high (churny boards) 2=medium (research/bid) 3=low (static/voc)
"""
from __future__ import annotations

from . import patterns as P

HOST = P.HOST

# (source_type, variant, board_seq, menu_seq, page_seq, book_gbn, extra, priority, label)
BOARDS = [
    ("board", "bs", 50, 583, None, None, None, 1, "공지사항/채용공고"),
    ("board", "job", 115, 997, None, None, None, 1, "채용공고"),
    ("board", "bs", 55, 585, None, None, None, 1, "행사안내"),
    ("board", "bs", 46, 596, None, None, None, 2, "정책자료"),
    ("board", "bs", 60, 579, None, None, None, 2, "스포츠교실"),
    ("board", "bs", 37, 682, None, None, {"keyKind3": "101"}, 2, "생활체육"),
    ("board", "bs", 40, 705, None, None, {"keyKind3": "H10"}, 2, "건강교실"),
    ("board", "bs", 56, 563, None, None, None, 3, "사회공헌"),
    ("board", "bs", 70, 837, None, None, None, 2, "글로벌스포츠프리즘"),
    ("board", "bs", 93, 951, None, None, None, 2, "스포츠 현안과 진단"),
    ("board", "ns", 81, 919, None, None, None, 2, "KISS미디어룸"),
    ("board", "bs", 105, 990, None, None, None, 2, "스포츠동향아카이브"),
    ("board", "bs", 104, 982, None, None, None, 2, "스포츠정책포럼"),
    ("board", "fq", 54, 592, None, None, None, 3, "자주하는질문(FAQ)"),
]

RESEARCH = [
    ("research", None, None, 594, None, None, None, 2, "연구보고서(orginList)"),
]

PUBLICATIONS = [
    ("pub", None, None, 844, None, "PS", None, 3, "정기간행물 PS"),
    ("pub", None, None, 845, None, "PI", None, 3, "정기간행물 PI"),
    ("pub", None, None, 843, None, "PP", None, 3, "정기간행물 PP"),
]

BID = [("bid", None, None, 713, None, None, None, 2, "입찰정보")]
VOC = [("voc", None, None, 716, None, None, None, 3, "고객의 소리")]

STATIC_PAGES = [
    ("static", None, None, 559, 27, None, None, 3, "원장 인사말"),
    ("static", None, None, 729, 142, None, None, 3, "과학원 소개"),
    ("static", None, None, 561, 29, None, None, 3, "사업분야"),
    ("static", None, None, 566, 26, None, None, 3, "찾아오시는 길"),
    ("static", None, None, 586, 48, None, None, 3, "KISS BI"),
    ("static", None, None, 647, 42, None, None, 3, "연구사업"),
    ("static", None, None, 652, 68, None, None, 3, "지원사업"),
    ("static", None, None, 674, 89, None, None, 3, "국제교류사업"),
    ("static", None, None, 930, 208, None, None, 3, "유네스코석좌사업"),
    ("static", None, None, 687, 125, None, None, 3, "국민건강체조"),
    ("static", None, None, 711, 50, None, None, 3, "유관기관소식/웹진"),
    ("static", None, None, 587, 130, None, None, 3, "전자민원"),
    ("static", None, None, 725, 132, None, None, 3, "과학원 견학안내"),
    ("static", None, None, 913, 198, None, None, 3, "연구제안"),
]

ALL_SEEDS = BOARDS + RESEARCH + PUBLICATIONS + BID + VOC + STATIC_PAGES


def load_seeds(store):
    for (stype, variant, board_seq, menu_seq, page_seq, book_gbn, extra, prio, label) in ALL_SEEDS:
        store.upsert_source(
            host=HOST, source_type=stype, variant=variant, board_seq=board_seq,
            menu_seq=menu_seq, page_seq=page_seq, book_gbn=book_gbn,
            extra_params=extra, list_url_tmpl=label, priority=prio)
