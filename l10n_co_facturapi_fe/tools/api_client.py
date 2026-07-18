import base64
import logging

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _to_str(value):
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="replace")
        if decoded.startswith("-----"):
            return decoded
        try:
            return base64.b64decode(decoded).decode("utf-8")
        except Exception:
            return decoded
    return value


class FacturAPIClient:

    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def get_numbering_range(self, nit, software_code, certificate, environment="produccion"):
        certificate.ensure_one()
        if not certificate.is_valid:
            raise UserError(_("Certificate is not valid."))
        if not certificate.private_key_id:
            raise UserError(_("Certificate has no private key."))

        cert_pem = _to_str(certificate.pem_certificate)
        key_pem = _to_str(certificate.private_key_id.pem_key)

        payload = {
            "nit": nit,
            "software_code": software_code,
            "certificate_pem": cert_pem,
            "private_key_pem": key_pem,
            "environment": environment,
        }

        url = f"{self.base_url}/api/v1/companies/numbering-range"
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            raise UserError(_("Cannot connect to FacturAPI server at %s") % self.base_url)
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text[:500]
            raise UserError(_("DIAN error: %s") % detail)
        except requests.exceptions.RequestException as e:
            raise UserError(_("Request failed: %s") % e)
