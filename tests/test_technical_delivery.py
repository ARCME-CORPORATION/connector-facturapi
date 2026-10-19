"""Offline tests of the real packaging method with minimal ORM doubles."""
import ast
import base64
import io
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "connector_facturapi/models/facturapi_document.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FacturapiDocument")
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {
    "_get_technical_delivery_attachment", "_get_dian_zip_attachment",
    "_get_delivery_pdf_content", "_refresh_delivery_zip_pdf",
}]
namespace = dict(base64=base64, io=io, zipfile=zipfile, datetime=datetime, timedelta=timedelta, timezone=timezone,
    re=__import__("re"), UserError=ValueError, _=lambda text: text)
exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), "exec"), namespace)
package_method = namespace["_get_technical_delivery_attachment"]
standard_package_method = namespace["_get_dian_zip_attachment"]


class Attachments:
    def __init__(self): self.records = []
    def __bool__(self): return False  # Empty ir.attachment recordset.
    def search(self, domain, limit=1):
        return next((r for r in self.records if all(
            getattr(r, k, None) == v for k, op, v in domain
        )), None)
    def create(self, values):
        result = SimpleNamespace(**values)
        result.write = lambda vals: result.__dict__.update(vals)
        self.records.append(result)
        return result


class Sequence:
    def __init__(self): self.counter = 0
    def sudo(self): return self
    def search(self, domain, limit=1): return self
    def next_by_id(self): self.counter += 1; return str(self.counter)


class Env:
    def __init__(self):
        self.attachments = Attachments()
        self.sequence = Sequence()
        self.locks = []
        self.cr = SimpleNamespace(execute=lambda sql,args: self.locks.append(sql))
    def __getitem__(self, name):
        return self.attachments if name == "ir.attachment" else self.sequence


def record(env, record_id=1, vat="901828321-3", state="accepted"):
    doc = SimpleNamespace(
        id=record_id, env=env, state=state,
        move_id=SimpleNamespace(id=record_id, name="FEV%s" % record_id,
                               invoice_pdf_report_id=SimpleNamespace(raw=b"%PDF Odoo invoice")),
        company_id=SimpleNamespace(id=1, name="Empresa", partner_id=SimpleNamespace(vat=vat)),
        attached_document=base64.b64encode(b"<AttachedDocument/>").decode(),
        pdf_file=base64.b64encode(b"%PDF-1.4 test").decode(), document_type="invoice",
        ensure_one=lambda:None, invalidate_recordset=lambda fields:None,
        _technical_delivery_enabled=lambda:False,
    )
    doc._get_delivery_pdf_content = lambda: namespace["_get_delivery_pdf_content"](doc)
    doc._refresh_delivery_zip_pdf = lambda *args: namespace["_refresh_delivery_zip_pdf"](doc, *args)
    doc._get_technical_delivery_attachment = lambda: package_method(doc)
    return doc


class TechnicalDeliveryTests(unittest.TestCase):
    def test_zip_has_own_software_names_and_two_files(self):
        env=Env(); doc=record(env)
        result=package_method(doc)
        year=datetime.now(timezone(timedelta(hours=-5))).year % 100
        stem="0901828321000%02d00000001" % year
        self.assertEqual(result.name, "z%s.zip" % stem)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result.datas))) as z:
            self.assertEqual(z.namelist(), ["ad%s.xml" % stem, "fv%s.pdf" % stem])
            self.assertEqual(z.read("ad%s.xml" % stem), b"<AttachedDocument/>")
            self.assertEqual(z.read("fv%s.pdf" % stem), doc.move_id.invoice_pdf_report_id.raw)

    def test_repeated_preparation_reuses_name_and_sequence(self):
        env=Env(); doc=record(env)
        first=package_method(doc)
        self.assertIs(package_method(doc), first)
        self.assertEqual(env.sequence.counter, 1)
        second=package_method(record(env, record_id=2))
        self.assertTrue(second.name.endswith("00000002.zip"))

    def test_rejected_document_cannot_be_delivered(self):
        env=Env()
        with self.assertRaises(ValueError): package_method(record(env,state="rejected"))
        self.assertEqual(env.sequence.counter, 0)

    def test_invalid_nit_is_rejected(self):
        with self.assertRaises(ValueError): package_method(record(Env(),vat="not-a-nit"))


class OdooInvoicePdfTests(unittest.TestCase):
    def _ready_document(self):
        doc = record(Env())
        doc.xml_signed = base64.b64encode(b"<Invoice/>")
        doc.application_response = "<ApplicationResponse/>"
        return doc

    def _assert_pdf(self, attachment, content):
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(attachment.datas))) as archive:
            pdfs = [name for name in archive.namelist() if name.endswith(".pdf")]
            self.assertEqual(len(pdfs), 1)
            self.assertEqual(archive.read(pdfs[0]), content)
            return {name: archive.read(name) for name in archive.namelist()}

    def test_standard_zip_uses_exact_odoo_pdf_instead_of_api_pdf(self):
        doc = self._ready_document()
        package = standard_package_method(doc)
        entries = self._assert_pdf(package, doc.move_id.invoice_pdf_report_id.raw)
        self.assertEqual(entries["FE_FEV1.xml"], b"<Invoice/>")
        self.assertEqual(entries["FE_FEV1_appresponse.xml"], b"<ApplicationResponse/>")

    def test_both_delivery_modes_wait_for_odoo_pdf(self):
        for method in (package_method, standard_package_method):
            with self.subTest(method=method.__name__):
                doc = self._ready_document()
                doc.move_id.invoice_pdf_report_id.raw = b""
                self.assertFalse(method(doc))
                self.assertEqual(doc.env.attachments.records, [])
                self.assertEqual(doc.env.sequence.counter, 0)
                doc.move_id.invoice_pdf_report_id.raw = b"%PDF selected by wizard"
                self._assert_pdf(method(doc), doc.move_id.invoice_pdf_report_id.raw)

    def test_cached_zips_replace_api_pdf_and_keep_names_and_xml(self):
        for method in (package_method, standard_package_method):
            with self.subTest(method=method.__name__):
                doc = self._ready_document()
                package = method(doc)
                before = self._assert_pdf(package, doc.move_id.invoice_pdf_report_id.raw)
                # Simulate a ZIP cached before the fix with the API PDF.
                raw = io.BytesIO()
                with zipfile.ZipFile(raw, "w") as archive:
                    for name, content in before.items():
                        archive.writestr(name, b"%PDF from API" if name.endswith(".pdf") else content)
                package.datas = base64.b64encode(raw.getvalue())
                original_name = package.name
                self.assertIs(method(doc), package)
                after = self._assert_pdf(package, doc.move_id.invoice_pdf_report_id.raw)
                self.assertEqual(after, before)
                self.assertEqual(package.name, original_name)
                self.assertEqual(len(doc.env.attachments.records), 1)
                # An unchanged Odoo PDF must not rewrite the cached package.
                original_data = package.datas
                self.assertIs(method(doc), package)
                self.assertEqual(package.datas, original_data)

    def test_sales_document_types_use_odoo_report(self):
        doc = self._ready_document()
        for kind in ("invoice", "credit_note", "debit_note"):
            doc.document_type = kind
            self.assertEqual(doc._get_delivery_pdf_content(), doc.move_id.invoice_pdf_report_id.raw)

    def test_support_documents_keep_their_existing_pdf_source(self):
        doc = self._ready_document()
        doc.document_type = "support_doc"
        self._assert_pdf(standard_package_method(doc), base64.b64decode(doc.pdf_file))


class BaseSender:
    def _get_mail_params(self, move, move_data):
        return {"attachments": move_data["attachments"], "subject": "Factura"}
    def _get_invoice_extra_attachments(self, move):
        return ["Odoo PDF"] if move.invoice_pdf_report_id else []
    def _get_placeholder_mail_attachments_data(self, move, **kwargs):
        return ["Odoo PDF placeholder"]


sender_tree = ast.parse((ROOT / "connector_facturapi_fe/models/account_move_send.py").read_text(encoding="utf-8"))
sender_cls = next(n for n in sender_tree.body if isinstance(n, ast.ClassDef))
mail_methods = [n for n in sender_cls.body if isinstance(n, ast.FunctionDef) and n.name in {
    "_get_mail_params", "_get_invoice_extra_attachments", "_get_placeholder_mail_attachments_data",
}]
for method in mail_methods:
    method.decorator_list = []
mail_cls = ast.ClassDef(name="Sender", bases=[ast.Name(id="BaseSender", ctx=ast.Load())], keywords=[], body=mail_methods, decorator_list=[])
module = ast.fix_missing_locations(ast.Module(body=[mail_cls], type_ignores=[]))
mail_namespace = dict(namespace, BaseSender=BaseSender)
exec(compile(module, "mail-test", "exec"), mail_namespace)
Sender = mail_namespace["Sender"]


class MailDeliveryTests(unittest.TestCase):
    def test_wizard_keeps_pdf_placeholder_until_odoo_generates_report(self):
        doc = SimpleNamespace(state="accepted", _technical_delivery_enabled=lambda:True)
        move = SimpleNamespace(connector_facturapi_document_id=doc, invoice_pdf_report_id=False)
        self.assertEqual(Sender()._get_placeholder_mail_attachments_data(move), ["Odoo PDF placeholder"])
        move.invoice_pdf_report_id = SimpleNamespace(name="Odoo.pdf")
        self.assertEqual(Sender()._get_placeholder_mail_attachments_data(move), [])

    def test_wizard_never_adds_api_pdf_before_package_is_ready(self):
        doc = SimpleNamespace(document_type="invoice", _get_dian_zip_attachment=lambda:False)
        move = SimpleNamespace(id=1, connector_facturapi_document_id=doc, invoice_pdf_report_id=False)
        searches = []
        def search(domain):
            searches.append(domain)
            return ["XML"]
        sender = Sender()
        sender.env = {"ir.attachment": SimpleNamespace(search=search)}
        self.assertEqual(sender._get_invoice_extra_attachments(move), ["XML"])
        self.assertEqual(len(searches), 1)
        self.assertIn(("mimetype", "=", "application/xml"), searches[0])

    def test_mail_without_package_keeps_odoo_attachments(self):
        doc = SimpleNamespace(_technical_delivery_enabled=lambda:True, _get_dian_zip_attachment=lambda:False)
        move = SimpleNamespace(connector_facturapi_document_id=doc)
        params = Sender()._get_mail_params(move, {"attachments": [("Odoo.pdf", b"%PDF Odoo")]})
        self.assertEqual(params["attachments"], [("Odoo.pdf", b"%PDF Odoo")])

    def test_mail_has_one_zip_and_pdf_only_inside(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as z:
            z.writestr("ad.xml", "<AttachedDocument/>")
            z.writestr("fv.pdf", b"%PDF-test")
        package = SimpleNamespace(name="ztechnical.zip", raw=raw.getvalue())
        doc = SimpleNamespace(_technical_delivery_enabled=lambda:True, _get_dian_zip_attachment=lambda:package)
        move = SimpleNamespace(name="FEV5", connector_facturapi_document_id=doc, invoice_pdf_report_id=SimpleNamespace(name="FEV5.pdf"))
        params = Sender()._get_mail_params(move, {"attachments": [("FEV5.pdf", b"duplicate"), (package.name, package.raw)]})
        self.assertEqual([name for name,content in params["attachments"]], [package.name])
        self.assertEqual(params["attachments"][0][1], package.raw)

    def test_complementary_user_attachment_is_preserved_in_zip(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, "w") as z: z.writestr("ad.xml", "<AttachedDocument/>")
        package = SimpleNamespace(name="ztechnical.zip", raw=raw.getvalue())
        doc = SimpleNamespace(_technical_delivery_enabled=lambda:True, _get_dian_zip_attachment=lambda:package)
        move = SimpleNamespace(name="FEV5", connector_facturapi_document_id=doc, invoice_pdf_report_id=False)
        params = Sender()._get_mail_params(move, {"attachments": [("soporte.txt", b"user-data")]})
        self.assertEqual(len(params["attachments"]), 1)
        with zipfile.ZipFile(io.BytesIO(params["attachments"][0][1])) as z:
            with zipfile.ZipFile(io.BytesIO(z.read("complementarios.zip"))) as extra:
                self.assertEqual(extra.read("soporte.txt"), b"user-data")


if __name__ == "__main__": unittest.main()
