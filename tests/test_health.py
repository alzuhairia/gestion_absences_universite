from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(
    HEALTHCHECK_ALLOWLIST_CIDRS=['127.0.0.1/32'],
    HEALTHCHECK_RATE_LIMIT='1000/m',
    HEALTHCHECK_TOKEN='current-token',
    HEALTHCHECK_VALID_TOKENS=['current-token', 'previous-token'],
)
class HealthcheckSecurityTests(TestCase):
    def setUp(self):
        self.url = reverse('health:health_check')

    def test_query_token_is_refused(self):
        response = self.client.get(f'{self.url}?token=current-token', secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_header_token_is_accepted(self):
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN='current-token',
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'status': 'ok'})

    def test_invalid_token_returns_403(self):
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN='wrong-token',
            secure=True,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_previous_rotated_token_is_accepted(self):
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN='previous-token',
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'status': 'ok'})
