from datetime import datetime

class CredibilityScorer:
    def score(self, source: dict, all_sources: list) -> int:
        score = 40  # 初始分數

        # 來自本人（假設無法判斷，跳過）
        # if source.get('source') == 'x' and 'elonmusk' in source.get('url', '').lower():
        #     score += 10

        # 與其他來源一致（檢查 URL 是否重複）
        content = source.get('content', '').lower()
        consistent = any(s.get('content', '').lower() in content or content in s.get('content', '').lower()
                         for s in all_sources if s != source)
        if consistent:
            score += 5

        # 歷史事實（無發布日期，跳過）
        # pub_date = source.get('published', '')
        # if pub_date:
        #     try:
        #         pub_datetime = datetime.strptime(pub_date, '%Y-%m-%d %H:%M %Z')
        #         age = (datetime.now() - pub_datetime).days / 365
        #         if age > 0.25:  # 3個月
        #             if age <= 1:
        #                 score += 5
        #             elif age <= 3:
        #                 score += 10
        #             else:
        #                 score += 15
        #     except ValueError:
        #         pass

        # 具體背景（檢查內容是否包含關鍵詞）
        if any(keyword in content.lower() for keyword in ['date', 'place', 'person', 'event']):
            score += 5

        # 可驗證證據（檢查 URL 是否為可信來源）
        if any(domain in source.get('url', '').lower() for domain in ['un.org', 'hrw.org', 'justice.gov']):
            score += 5

        # 邏輯因果（檢查內容是否包含因果詞）
        if 'because' in content.lower() or 'due to' in content.lower():
            score += 5

        return score