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
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_get_technical_delivery_attachment")
namespace = dict(base64=base64, io=io, zipfile=zipfile, datetime=datetime, timedelta=timedelta, timezone=timezone,
    re=__import__("re"), UserError=ValueError, _=lambda text: text)
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
package_method = namespace[method.name]


class Attachments:
    def __init__(self): self.records = []
    def search(self, domain, limit=1):
        marker = next(v for k,op,v in domain if k == "description")
        return next((r for r in self.records if r.description == marker), None)
    def create(self, values):
        result = SimpleNamespace(**values)
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
    return SimpleNamespace(
        id=record_id, env=env, state=state, move_id=SimpleNamespace(id=record_id),
        company_id=SimpleNamespace(id=1, name="Empresa", partner_id=SimpleNamespace(vat=vat)),
        attached_document=base64.b64encode(b"<AttachedDocument/>").decode(),
        pdf_file=base64.b64encode(b"%PDF-1.4 test").decode(), document_type="invoice",
        ensure_one=lambda:None, invalidate_recordset=lambda fields:None,
    )


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
            self.assertEqual(z.read("fv%s.pdf" % stem), b"%PDF-1.4 test")

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


class BaseSender:
    def _get_mail_params(self, move, move_data):
        return {"attachments": move_data["attachments"], "subject": "Factura"}


sender_tree = ast.parse((ROOT / "connector_facturapi_fe/models/account_move_send.py").read_text(encoding="utf-8"))
sender_cls = next(n for n in sender_tree.body if isinstance(n, ast.ClassDef))
mail_method = next(n for n in sender_cls.body if isinstance(n, ast.FunctionDef) and n.name == "_get_mail_params")
mail_method.decorator_list = []
mail_cls = ast.ClassDef(name="Sender", bases=[ast.Name(id="BaseSender", ctx=ast.Load())], keywords=[], body=[mail_method], decorator_list=[])
module = ast.fix_missing_locations(ast.Module(body=[mail_cls], type_ignores=[]))
mail_namespace = dict(namespace, BaseSender=BaseSender)
exec(compile(module, "mail-test", "exec"), mail_namespace)
Sender = mail_namespace["Sender"]


class MailDeliveryTests(unittest.TestCase):
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
