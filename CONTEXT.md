# Odoo — Contexto de Modulos de Facturacion Electronica

## Que es esta carpeta

Modulos Odoo 18 para integrar facturacion electronica colombiana (DIAN) via el backend `facturapi-api`. El backend esta en el repo separado `facturapi/`.

---

## Modulos

```
connector-facturapi/
├── connector_facturapi/          # Base: certificado, config empresa, modelo facturapi.document, payload builder
└── connector_facturapi_fe/       # FE: botones, wizard, secuencias, reporte PDF, cron auto-envio
```

### Dependencias
```
connector_facturapi  (depende de: account, base_address_extended, certificate, uom, base_vat,
                       l10n_co_verification_digit, l10n_co_economic_activities, l10n_co_withholding)
        │
connector_facturapi_fe  (depende de: connector_facturapi, account_move_name_sequence)
```

`connector_facturapi` excluye `l10n_co_electronic_invoice` y `l10n_co_electronic_invoice_self`.

---

## Tipos de documento soportados

| Move type (Odoo) | Documento DIAN | TypeCode |
|------------------|----------------|----------|
| `out_invoice` | Factura de Venta (`invoice`) | 01 |
| `out_refund` | Nota Credito (`credit_note`) | 91 |
| `out_debit` / `out_invoice` con `debit_origin_id` | Nota Debito (`debit_note`) | 92 |
| `in_invoice` | Documento Soporte (`support_doc`) | 05 |
| `in_refund` | Nota Credito DS (`support_doc_credit_note`) | 95 |

El tipo lo resuelve `_get_document_type(move)` en `facturapi_document.py`. El tipo de operacion (20/22/30/32/10) lo resuelve `_get_operation_type()`.

---

## Auth — Multi-tenant

El token Bearer tiene formato `company_id:api_key`:

```python
# En _get_headers() de facturapi_document.py:
token = f"{company.facturapi_company_id}:{company.facturapi_api_key}"
headers = {"Authorization": f"Bearer {token}"}
```

- `facturapi_company_id`: UUID de la empresa en FacturAPI (configurar en Settings)
- `facturapi_api_key`: UUID auto-generado por la API (configurar en Settings)
- La API valida que ambos existan y coincidan en su DB

---

## Configuracion de empresa

Campos en `res.company` (editables desde `res.config.settings` via related):

- `facturapi_api_url` — URL del backend (default `http://host.docker.internal:8000`)
- `facturapi_company_id` — UUID del tenant en FacturAPI
- `facturapi_api_key` — API key (UUID)
- `connector_dian_environment` — `habilitacion` (default) o `produccion`
- `certificate_id` — Many2one a `certificate.certificate` (scope=facturapi)
- `connector_software_id` — Software ID DIAN
- `connector_software_pin` — PIN del software (se almacena cifrado)
- `connector_test_set_id` — Test Set ID (obligatorio en habilitacion)
- `connector_fe_auto_send` — auto-envio FE por cron (`_cron_facturapi_fe_auto_send`)

---

## Certificados

Los certificados se gestionan desde el modulo `certificate` de Odoo (PFX upload, normalizacion a PEM). El conector agrega un scope `"facturapi"`.

**Flujo:**
1. Usuario sube PFX en **Settings > Certificados** (modulo `certificate`)
2. Selecciona el certificado en el formulario de empresa (Facturacion Electronica)
3. Presiona **"Enviar Certificado a API"** → envia PEM a `POST /api/v1/companies/{company_id}/certificate`
4. La API lo almacena en su DB y lo usa para firmar y enviar a DIAN

---

## Modulo Base: `connector_facturapi`

### Modelos
- **`facturapi.document`** — Tabla principal que registra cada documento enviado a DIAN. Estados: `to_send` → `processing` → `accepted` / `rejected`. Campos: `document_type`, `task_id`, `cufe`, `qr_code`, `xml_signed`, `pdf_file`, `application_response`, `dian_status`, `dian_message`, `error_message`, `dian_error_details`, `connector_dian_accepted_datetime`, `is_cancel`.
- **`certificate.certificate`** — heredada, scope `"facturapi"`

### Metodos clave (`facturapi_document.py`)
- `_post_to_web_service()` — arma el payload (`_build_facturapi_payload`) y hace `POST /documents/submit`; guarda `task_id` y `document_type`
- `_check_task_status()` / `_fetch_and_process_result()` — consultan `/documents/{task_id}/status|result` y actualizan el documento
- `_get_dian_zip_attachment()` — genera el ZIP (XML + ApplicationResponse + PDF)
- `_parse_dian_rejection()` — extrae motivos de rechazo del XML de respuesta

### Hooks del pipeline EDI (base)
- `_get_ubl_cii_builder_from_xml_tree` (`account_move.py`) — detecta XML DIAN (CustomizationID "10" / UBL 2.1) para el pipeline `account_edi_ubl_cii`
- `_message_post_after_hook` (`account_move.py`) — log de adjuntos en emails provenientes del alias
- `ir_attachment.py` — `_decode_edi_zip`/`_is_connector_zip`/`_get_edi_supported_formats`: decodifican ZIP de DIAN (XML + PDF + ApplicationResponse) para el pipeline EDI y los emails de proveedores

### Envio del payload
- Resolucion y llave tecnica desde `ir.sequence.date_range` (`_get_active_sequence_range`)
- Fechas de resolucion enviadas: `dian_resolution_date`/`dian_resolution_date_to`, con fallback a `date_from`/`date_to` del rango (NO usar `context_today`: DIAN rechaza con **FAB07b/FAB08b** si no coinciden con la vigencia del rango registrado).
  - En habilitacion la resolucion estandar es `18760000001`, rango `990000000-995000000`, llave `fc8eac422eba16e22ffd8c6f94b3f40a6e38162c`, vigencia `2019-01-19` → `2030-01-19`.
- DIAN exige que la `issue_date` del documento sea igual a la fecha de envio/firma (regla **FAD09e**): reenviar una factura fechada en dias anteriores es rechazado. En habilitacion emitir/sincronizar la factura el mismo dia en que se envia.
- Para NC/ND se incluyen `billing_reference_id`, `billing_reference_cufe`, `billing_reference_date`, `discrepancy_response_code`
- Moneda extranjera: `original_currency` + `exchange_rate` (COP por unidad)
- Retenciones: separadas en `withholding_tax_totals` (codigos 05/06/07/08)

---

## Modulo FE: `connector_facturapi_fe`

### Funcionalidad
- Botones en facturas: "Send to DIAN", "Resend to DIAN", "Check DIAN Status", "Cancel DIAN", "DIAN Get Status", "DIAN Get Status Event", "DIAN Get XML", "DIAN Get Reference Notes"
- Wizard de envio (`account_move_send.py`)
- Secuencias de numeracion por rango de fechas (`ir_sequence_date_range.py`)
- Reporte PDF de factura electronica (`report/`)
- Cron de auto-envio (`connector_fe_auto_send`)
- Consultas DIAN directas via `_dian_query()` (`/documents/dian/get-status`, etc.)

### Importacion de facturas de proveedor por CUFE (`account_move.py`)
- Campo `connector_import_cufe` en `account.move` + boton "Importar por CUFE" (visible en `in_invoice`/`in_refund` en borrador, vista `views/account_move_views.xml`)
- `action_connector_import_by_cufe()`: llama `POST /documents/dian/get-xml-by-document-key` (SOAP `GetXmlByDocumentKey` con el certificado de la empresa), guarda el ZIP como adjunto y ejecuta el pipeline EDI nativo (`_extend_with_attachments`) que decodifica el ZIP (`_decode_edi_zip`, que vive en el modulo base) y llena partner, lineas e impuestos via UBL 2.1
- Requiere: factura sin lineas, FacturAPI configurado en la empresa, y que la empresa figure como adquiriente del documento en DIAN
- Nota: los hooks del pipeline EDI (`_get_ubl_cii_builder_from_xml_tree`, `ir_attachment` ZIP, `_message_post_after_hook`) viven en el modulo base para que la decodificacion funcione en todos los clientes

### Campos en `account.move` (related a `facturapi.document`)
- `connector_facturapi_document_id`, `connector_facturapi_state`
- `connector_dian_status_code`, `connector_dian_error`, `connector_dian_error_details`
- `connector_dian_task_id`, `connector_dian_accepted_datetime`
- `connector_cufe`, `connector_qr_code`, `connector_xml_signed`, `connector_application_response`
- `connector_sequence_range_id`, `connector_dian_invoice_type_code`

---

## Integracion con el backend

1. `POST {facturapi_api_url}/api/v1/documents/submit` (Bearer `company_id:api_key`) → devuelve `task_id`
2. El worker del backend genera XML, CUFE/CUDS, firma, ZIP y envia a DIAN
3. **Habilitacion:** `SendTestSetAsync` + `test_set_id` + sondeo `GetStatusZip` (el `test_set_id` es obligatorio en habilitacion)
4. **Produccion:** `SendBillSync`
5. Odoo consulta `/documents/{task_id}/status` y `/documents/{task_id}/result` para actualizar

---

## Convenciones Odoo 18 (CRITICO)

### XML
- Usar `<list>` en vez de `<tree>`
- Usar expresiones `invisible` en vez de `attrs`:
  ```xml
  <!-- MAL (Odoo 16/17) -->
  <field name="foo" attrs="{'invisible': [('state', '=', 'draft')]}"/>

  <!-- BIEN (Odoo 18) -->
  <field name="foo" invisible="state == 'draft'"/>
  ```
- NO usar literal `false` en `invisible` — usar `not field_name` o `field_name == False`
- NO usar `<data>` wrapper dentro de `<odoo>`
- NO usar `states=` en campos — usar `invisible` con condiciones

### Python
- Heredar de `models.Model` normalmente
- Usar `api.depends` para computed fields
- No duplicar logica DIAN en Odoo: el XML/CUFE/firma viven en el backend `facturapi/`

---

## Infraestructura Docker Odoo

**Docker Compose:** `C:\Users\jupar\Documents\GitHub\juanparmer\compose.yaml`

| Container | Puerto | DB User/Pass/DB |
|-----------|--------|-----------------|
| `odoo-web-1` | 8069 | — |
| `odoo-db-1` | 5432 | `odoo`/`odoo`/`admin` |

Los modulos se montan por bind mount en `/mnt/extra-addons/connector-facturapi` (rw). Cambios en Python requieren recargar: `docker exec -i odoo-web-1 odoo -d admin -u <modulo> --stop-after-init` (o reiniciar el contenedor).

### Instalar un modulo
```bash
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi --stop-after-init
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi_fe --stop-after-init
```

---

## COMO PROBAR

### Verificar que los modulos estan instalados
```sql
SELECT name, state FROM ir_module_module WHERE name LIKE 'connector_facturapi%';
```

### Verificar configuracion de empresa
```sql
SELECT name, facturapi_company_id, connector_dian_environment, connector_test_set_id
FROM res_company WHERE facturapi_company_id IS NOT NULL;
```

### Verificar documentos enviados
```sql
SELECT name, state, document_type, dian_status, task_id
FROM facturapi_document ORDER BY create_date DESC LIMIT 20;
```

---

## Pendiente

- [ ] Modulo DE (`connector_facturapi_de`) — Documento Equivalente
- [ ] Modulo NE (`connector_facturapi_ne`) — Nomina Individual
- [ ] Modulo RADIAN (`connector_facturapi_radian`) — Eventos
- [ ] Tests automatizados
- [ ] Boton "Consultar Rangos" desde Odoo hacia `POST /companies/numbering-range`
