import json
import httpx
import pytest
from app.core.config import Settings
from app.services.document_analysis import extract, AnalysisFailure


def test_provider_schema_and_local_validation():
    def handler(request):
        config = json.loads(request.content)['generationConfig']
        assert 'responseJsonSchema' not in config
        schema = config['responseSchema']
        field = schema['properties']['fields']['items']
        assert field['properties']['value']['nullable'] is True
        assert len(field['properties']['name']['enum']) == 24
        assert '$ref' not in json.dumps(schema)
        # Provider-compatible schema does not replace strict local validation.
        return httpx.Response(200, json={'candidates': [{'finishReason': 'STOP',
            'content': {'parts': [{'text': json.dumps({'fields': [], 'unexpected': True})}]}}]})
    with pytest.raises(AnalysisFailure) as exc:
        extract(Settings(), 'test', [], [], {}, transport=httpx.MockTransport(handler))
    assert exc.value.code == 'AI_INVALID_RESPONSE'


def test_bad_request_has_specific_error():
    with pytest.raises(AnalysisFailure) as exc:
        extract(Settings(), 'test', [], [], {},
                transport=httpx.MockTransport(lambda request: httpx.Response(400)))
    assert exc.value.code == 'AI_REQUEST_INVALID'
