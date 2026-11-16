import pytest
from test_automatic_review_v18 import setup, HTML, CONFIGS, NOW
from crawler import automatic_review as automatic, opportunity_review as review


class ClassifiedFailure(ValueError):
    def __init__(self, retryable):
        # Deliberately use wording that would produce the opposite legacy result.
        super().__init__('生成时限已到' if retryable else 'AI服务网络配置拒绝')
        self.code = 'total_timeout' if retryable else 'http_401'
        self.retryable = retryable


@pytest.mark.parametrize('retryable', [True, False])
def test_publisher_obeys_transport_classification_without_publishing(setup, retryable):
    root, queue, process = setup
    def fail(*args):
        raise ClassifiedFailure(retryable)
    result = process(checker=fail)
    assert result['state'] == ('retry' if retryable else 'manual_required')
    assert result['retryable'] is retryable and result['error_code'] == ClassifiedFailure(retryable).code
    assert not (root/'data/opportunities.json').exists()


@pytest.mark.parametrize('retryable', [True, False])
def test_assistance_obeys_classification_without_changing_facts(setup, retryable):
    root, queue, _ = setup
    before = review.read_queue(queue)['drafts'][0]['item']
    raw = HTML.replace(b'</article>', '<p>具体入营安排另行通知。</p></article>'.encode())
    def fail(*args):
        raise ClassifiedFailure(retryable)
    result = automatic.run(root, queue, CONFIGS, limit=1, publish=True, now=NOW,
                           fetcher=lambda _: raw, assistant=fail)['results'][0]
    assert result['state'] == ('retry' if retryable else 'manual_required')
    assert result['assistance']['retryable'] is retryable
    assert review.read_queue(queue)['drafts'][0]['item'] == before
    assert not (root/'data/opportunities.json').exists()
