import io
import logging
import zipfile

from odoo import models

_logger = logging.getLogger(__name__)


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _decode_edi_zip(self, filename, content):
        """Decode a ZIP file (DIAN package) into individual XML and PDF files.

        DIAN electronic invoicing packages typically contain:
        - Signed XML (the invoice XML)
        - PDF representation
        - ApplicationResponse (DIAN acknowledgment)

        This method extracts all files from the ZIP and returns them as
        individual file_data entries so the standard EDI pipeline can
        process the XML and PDF separately.
        """
        to_process = []
        try:
            buffer = io.BytesIO(content)
            with zipfile.ZipFile(buffer, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    file_content = zf.read(info.filename)
                    file_name = info.filename

                    # Determine file type from extension or content
                    lower_name = file_name.lower()
                    if lower_name.endswith(".xml"):
                        decoded = self._decode_edi_xml(file_name, file_content)
                        for entry in decoded:
                            entry["sort_weight"] = 10
                        to_process.extend(decoded)
                    elif lower_name.endswith(".pdf"):
                        decoded = self._decode_edi_pdf(file_name, file_content)
                        to_process.extend(decoded)
                    else:
                        # ApplicationResponse or other files: store as binary
                        to_process.append({
                            "filename": file_name,
                            "content": file_content,
                            "attachment": self,
                            "sort_weight": 100,
                            "type": "binary",
                        })
        except zipfile.BadZipFile:
            _logger.info("File %s is not a valid ZIP archive.", filename)
            return []

        return to_process

    def _is_connector_zip(self):
        """Check if this attachment is a ZIP file (DIAN package)."""
        if self.mimetype in ("application/zip", "application/x-zip-compressed"):
            return True
        if self.name and self.name.lower().endswith(".zip"):
            return True
        return False

    def _get_edi_supported_formats(self):
        """Add ZIP format support before standard formats.

        DIAN electronic invoicing sends ZIP packages containing XML + PDF
        + ApplicationResponse. This decoder extracts the individual files
        so the standard EDI pipeline can process them.
        """
        return [
            {
                "format": "connector_zip",
                "check": lambda attachment: attachment._is_connector_zip(),
                "decoder": self._decode_edi_zip,
            },
        ] + super()._get_edi_supported_formats()
