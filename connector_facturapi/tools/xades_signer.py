import base64
import uuid
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from lxml import etree


NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
NS_SIGNED_PROPS = "http://uri.etsi.org/01903/v1.3.2#SignedProperties"


class XadesSigner:

    def __init__(self, cert_pem, key_pem, key_password=None):
        self.cert = x509.load_pem_x509_certificate(cert_pem)
        self.private_key = serialization.load_pem_private_key(key_pem, password=key_password)
        self._is_rsa = isinstance(self.private_key, rsa.RSAPrivateKey)

    @classmethod
    def from_certificate(cls, certificate):
        certificate.ensure_one()
        if not certificate.is_valid:
            raise ValueError("Certificate is not valid")
        if not certificate.private_key_id:
            raise ValueError("Certificate has no private key")
        cert_pem = certificate.pem_certificate
        key_pem = certificate.private_key_id.pem_key
        return cls(cert_pem=cert_pem, key_pem=key_pem)

    @staticmethod
    def _calculate_digest(node):
        c14n = etree.tostring(node, method="c14n", exclusive=True, with_comments=False, strip_text=False)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(c14n)
        return base64.b64encode(digest.finalize()).decode("utf-8")

    def _der_to_raw_ecdsa(self, der_signature):
        r, s = decode_dss_signature(der_signature)
        key_size = (self.private_key.curve.key_size + 7) // 8
        return r.to_bytes(key_size, "big") + s.to_bytes(key_size, "big")

    def _build_qualifying_properties(self, signature_node, sig_id, props_id):
        object_node = etree.SubElement(signature_node, etree.QName(NS_DS, "Object"))
        qualifying = etree.SubElement(
            object_node, etree.QName(NS_XADES, "QualifyingProperties"), Target=f"#{sig_id}",
        )
        signed_props = etree.SubElement(
            qualifying, etree.QName(NS_XADES, "SignedProperties"), Id=props_id,
        )
        signed_sig_props = etree.SubElement(signed_props, etree.QName(NS_XADES, "SignedSignatureProperties"))

        now = datetime.now(timezone.utc)
        etree.SubElement(signed_sig_props, etree.QName(NS_XADES, "SigningTime")).text = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        signing_cert = etree.SubElement(signed_sig_props, etree.QName(NS_XADES, "SigningCertificate"))
        cert_node = etree.SubElement(signing_cert, etree.QName(NS_XADES, "Cert"))
        cert_digest_node = etree.SubElement(cert_node, etree.QName(NS_XADES, "CertDigest"))
        etree.SubElement(cert_digest_node, etree.QName(NS_DS, "DigestMethod"), Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")

        cert_hash = hashes.Hash(hashes.SHA256())
        cert_hash.update(self.cert.public_bytes(serialization.Encoding.DER))
        etree.SubElement(cert_digest_node, etree.QName(NS_DS, "DigestValue")).text = base64.b64encode(cert_hash.finalize()).decode("utf-8")

        issuer_serial = etree.SubElement(cert_node, etree.QName(NS_XADES, "IssuerSerial"))
        etree.SubElement(issuer_serial, etree.QName(NS_DS, "X509IssuerName")).text = self.cert.issuer.rfc4514_string()
        etree.SubElement(issuer_serial, etree.QName(NS_DS, "X509SerialNumber")).text = str(self.cert.serial_number)

        return self._calculate_digest(signed_props)

    def sign_xml(self, xml_bytes):
        root = etree.fromstring(xml_bytes)
        sig_id = f"signature-{uuid.uuid4()}"
        props_id = f"signedprops-{uuid.uuid4()}"
        ref_id = f"reference-{uuid.uuid4()}"

        sig_alg = (
            "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
            if self._is_rsa
            else "http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"
        )

        signature = etree.SubElement(root, etree.QName(NS_DS, "Signature"), Id=sig_id, nsmap={
            "ds": NS_DS,
            "xades": NS_XADES,
        })

        signed_info = etree.SubElement(signature, etree.QName(NS_DS, "SignedInfo"))
        etree.SubElement(signed_info, etree.QName(NS_DS, "CanonicalizationMethod"), Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
        etree.SubElement(signed_info, etree.QName(NS_DS, "SignatureMethod"), Algorithm=sig_alg)

        ref1 = etree.SubElement(signed_info, etree.QName(NS_DS, "Reference"), Id=ref_id, URI="")
        transforms = etree.SubElement(ref1, etree.QName(NS_DS, "Transforms"))
        etree.SubElement(transforms, etree.QName(NS_DS, "Transform"), Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature")
        etree.SubElement(transforms, etree.QName(NS_DS, "Transform"), Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
        etree.SubElement(ref1, etree.QName(NS_DS, "DigestMethod"), Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
        digest1 = etree.SubElement(ref1, etree.QName(NS_DS, "DigestValue"))

        ref2 = etree.SubElement(signed_info, etree.QName(NS_DS, "Reference"), Type=NS_SIGNED_PROPS, URI=f"#{props_id}")
        transforms2 = etree.SubElement(ref2, etree.QName(NS_DS, "Transforms"))
        etree.SubElement(transforms2, etree.QName(NS_DS, "Transform"), Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#")
        etree.SubElement(ref2, etree.QName(NS_DS, "DigestMethod"), Algorithm="http://www.w3.org/2001/04/xmlenc#sha256")
        digest2 = etree.SubElement(ref2, etree.QName(NS_DS, "DigestValue"))

        nsmap = {"ds": NS_DS}
        temp_root = etree.fromstring(etree.tostring(root))
        for sig in temp_root.xpath("./ds:Signature", namespaces=nsmap):
            sig.getparent().remove(sig)
        digest1.text = self._calculate_digest(temp_root)

        digest2.text = self._build_qualifying_properties(signature, sig_id, props_id)

        signed_info_c14n = etree.tostring(signed_info, method="c14n", exclusive=True, with_comments=False)
        if self._is_rsa:
            sig_value = self.private_key.sign(signed_info_c14n, padding.PKCS1v15(), hashes.SHA256())
        else:
            der_sig = self.private_key.sign(signed_info_c14n, ec.ECDSA(hashes.SHA256()))
            sig_value = self._der_to_raw_ecdsa(der_sig)

        etree.SubElement(signature, etree.QName(NS_DS, "SignatureValue")).text = base64.b64encode(sig_value).decode("utf-8")

        key_info = etree.SubElement(signature, etree.QName(NS_DS, "KeyInfo"))
        x509_data = etree.SubElement(key_info, etree.QName(NS_DS, "X509Data"))
        cert_pem_str = self.cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
        cert_b64 = "".join(cert_pem_str.splitlines()[1:-1])
        etree.SubElement(x509_data, etree.QName(NS_DS, "X509Certificate")).text = cert_b64

        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=False)
