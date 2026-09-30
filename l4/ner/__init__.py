"""KLUE-BERT 기반 한국어 NER.

L3(Presidio)는 spaCy 한국어 NER 파이프라인이 없어 한국어 인명을 탐지하지 못한다.
L4가 그 공백을 메운다.

`klue/bert-base`는 NER 헤드가 없는 MLM 인코더이므로 2단계로 학습한다.
  1차: KLUE-NER 공개 데이터로 헤드 학습 (이 패키지)
  2차: 이커머스 CS 데이터로 도메인 파인튜닝
"""
