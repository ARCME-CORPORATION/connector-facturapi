# connector-facturapi

Módulos Odoo 18 para facturación electrónica colombiana (DIAN) integrados vía el backend [FacturAPI](https://github.com/juanparmer/facturapi).

## Módulos

```
connector_facturapi/        # Base: certificado, config empresa, modelo facturapi.document, payload builder
connector_facturapi_fe/     # FE: botones, wizard de envío, secuencias, reporte PDF, cron auto-envío
```

### Dependencias

```
connector_facturapi  (depende de: account, base_address_extended, certificate, uom, base_vat,
                       l10n_co_verification_digit, l10n_co_economic_activities, l10n_co_withholding)
        │
connector_facturapi_fe  (depende de: connector_facturapi, account_move_name_sequence)
```

`connector_facturapi` excluye `l10n_co_electronic_invoice` y `l10n_co_electronic_invoice_self`.

## Requisitos

- Odoo 18
- Python 3.10+
- Backend FacturAPI corriendo (URL, company UUID y API key)
- Certificado digital DIAN (PFX) subido al backend
- Ambiente **habilitación**: `Test Set ID` configurado en la empresa

## Instalación

```bash
# Instalar módulo base
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi --stop-after-init

# Instalar FE completo
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi_fe --stop-after-init
```

También se puede instalar desde Apps > Buscar "FacturAPI" > Instalar.

## Configuración

En **Ajustes > FacturAPI** (campos related sobre `res.company`):

| Campo | Descripción |
|-------|-------------|
| `facturapi_api_url` | URL del backend (ej. `http://host.docker.internal:8000`) |
| `facturapi_company_id` | UUID del tenant en FacturAPI |
| `facturapi_api_key` | Clave de autenticación (UUID) |
| `connector_dian_environment` | `habilitacion` o `produccion` |
| `certificate_id` | Certificado digital DIAN (`scope=facturapi`) |
| `connector_software_id` | Software ID asignado por DIAN |
| `connector_software_pin` | PIN del software |
| `connector_test_set_id` | Test Set ID (obligatorio en habilitación) |
| `connector_fe_auto_send` | Auto-envío de facturas confirmadas (cron) |

Nota: en ambiente `habilitacion` el `test_set_id` es obligatorio; DIAN rechaza el envío del set de pruebas sin él.

## Tipos de documento soportados

| Move type (Odoo) | Documento DIAN | TypeCode | Operación SOAP |
|------------------|----------------|----------|----------------|
| `out_invoice` | Factura de Venta (`invoice`) | 01 | `SendBillSync` |
| `out_refund` | Nota Crédito (`credit_note`) | 91 | `SendBillSync` |
| `out_debit` (o `out_invoice` con `debit_origin_id`) | Nota Débito (`debit_note`) | 92 | `SendBillSync` |
| `in_invoice` | Documento Soporte (`support_doc`) | 05 | `SendBillSync` |
| `in_refund` | Nota Crédito DS (`support_doc_credit_note`) | 95 | `SendBillSync` |

En ambiente `habilitacion` con `test_set_id` configurado, el worker envía vía **`SendTestSetAsync`** y sondea **`GetStatusZip`** hasta obtener el resultado del lote.

## Flujo de envío

1. Confirmar la factura (posted).
2. Click en **"Send to DIAN"** → se crea un `facturapi.document` (`state=to_send`) y se hace `POST /api/v1/documents/submit`.
3. El backend responde un `task_id`; el documento pasa a `processing`.
4. El worker de FacturAPI genera el XML, calcula CUFE/CUDS, firma (XAdES), empaqueta en ZIP y envía a DIAN.
5. Odoo actualiza el estado con **"Check DIAN Status"** (`_check_task_status` → `_fetch_and_process_result`) o por cron.
6. Al ser aceptado (dian_status `00`), se guardan CUFE, QR, PDF, XML firmado y el ZIP adjunto.

### Botones disponibles en la factura

- **Send to DIAN** / **Resend to DIAN** (solo si fue rechazada)
- **Check DIAN Status** — consulta el resultado de la tarea en el backend
- **Cancel DIAN** — crea un documento de anulación (`is_cancel=True`)
- **DIAN Get Status** / **DIAN Get Status Event** — consultas SOAP directas
- **DIAN Get XML** — descarga el XML/ApplicationResponse desde DIAN
- **DIAN Get Reference Notes** — notas de referencia DIAN

## Campos en `account.move`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `connector_facturapi_document_id` | Many2one | Último `facturapi.document` del move |
| `connector_facturapi_state` | Selection | Estado del documento DIAN (to_send/processing/accepted/rejected) |
| `connector_dian_status_code` | Char | Código de estado DIAN (`00` aceptado, `99` rechazado, etc.) |
| `connector_dian_error` / `connector_dian_error_details` | Text | Errores DIAN |
| `connector_dian_task_id` | Char | Task ID del backend FacturAPI |
| `connector_dian_accepted_datetime` | Datetime | Fecha/hora de aceptación DIAN |
| `connector_cufe` | Char | CUFE/CUDS calculado |
| `connector_qr_code` | Text | QR en base64 |
| `connector_xml_signed` | Text | XML firmado (base64) |
| `connector_application_response` | Text | Respuesta de aplicación DIAN |
| `connector_sequence_range_id` | Many2one | Rango de numeración DIAN |
| `connector_dian_invoice_type_code` | Selection | Tipo de factura DIAN (01/02/03/04) |

## Modelo `facturapi.document`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `name` | Char | Referencia del documento |
| `move_id` | Many2one | Factura asociada |
| `company_id` | Many2one | Compañía |
| `state` | Selection | `to_send` → `processing` → `accepted` / `rejected` |
| `is_cancel` | Boolean | Es un documento de anulación |
| `document_type` | Selection | invoice / credit_note / debit_note / support_doc / support_doc_credit_note |
| `task_id` | Char | Task ID del backend |
| `cufe` / `qr_code` / `xml_signed` / `pdf_file` | Text | Resultados de DIAN |
| `dian_status` / `dian_message` | Char/Text | Código y mensaje de estado DIAN |
| `error_message` / `dian_error_details` | Text | Errores |

Acciones del modelo: `action_check_status`, `action_fetch_result`, `action_retry`; cron `_cron_check_dian_status`.

## Autenticación

Token Bearer con formato `company_id:api_key`:

```
Authorization: Bearer 3896c0f0-8d0d-4036-ba1d-46dd8dd14dd1:eb49aaa9-a2fd-40ae-abf3-68e483d6e731
```

Se envía en el header de todas las llamadas al backend (`_get_headers()` en `facturapi_document.py`).

## Verificación

```sql
-- Módulos instalados
SELECT name, state FROM ir_module_module WHERE name LIKE 'connector_facturapi%';

-- Config de empresa
SELECT name, facturapi_company_id, connector_dian_environment, connector_test_set_id
FROM res_company WHERE facturapi_company_id IS NOT NULL;

-- Documentos enviados
SELECT name, state, document_type, dian_status, cufe FROM facturapi_document
ORDER BY create_date DESC LIMIT 20;
```

## Convenciones Odoo 18

- Usar `<list>` en vez de `<tree>`
- Usar `invisible="condición"` en vez de `attrs`
- No usar `states=`; usar `invisible` con condiciones
- No usar wrapper `<data>` dentro de `<odoo>`

## Licencia

LGPL-3
