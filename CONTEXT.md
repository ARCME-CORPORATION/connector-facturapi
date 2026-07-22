# Odoo — Contexto de Modulos de Facturacion Electronica

## Que es esta carpeta

Modulos Odoo 18 para integrar facturacion electronica colombiana (DIAN) via la API `facturapi-api`. Cada tipo de documento electronico tiene su propio modulo.

---

## Modulos

```
connector-facturapi/
├── connector_facturapi/          # Base: certificado, config empresa, formato EDI, modelo facturapi.document
├── connector_facturapi_data/     # Datos: ciudades, tablas DIAN (medios_pago, responsable_fiscal, etc.)
├── connector_facturapi_fe/       # FE: Factura Electronica (botones, wizard, secuencias, reportes)
├── connector_facturapi_ds/       # DS: Documento Soporte (adquisiciones a no obligados)
├── connector_facturapi_de/       # DE: Documento Equivalente (PENDIENTE)
├── connector_facturapi_nom/      # NOM: Nomina Individual (PENDIENTE — usar OCA payroll)
└── connector_facturapi_radian/   # RADIAN: Eventos (PENDIENTE)
```

### Dependencias entre modulos
```
connector_facturapi_data  (sin dependencias)
        │
connector_facturapi  (depende de: account, account_edi, certificate, account_edi_ubl_cii)
   │        │
   │   connector_facturapi_fe  (depende de: connector_facturapi, connector_facturapi_data, account_move_name_sequence)
   │        │
   │   connector_facturapi_ds  (depende de: connector_facturapi, connector_facturapi_data, connector_facturapi_fe)
```

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

## Certificados

Los certificados se gestionan desde el modulo `certificate` de Odoo (PFX upload, normalizacion a PEM). El conector agrega un scope `"facturapi"`.

**Flujo:**
1. Usuario sube PFX en **Settings > Certificados** (usando el modulo `certificate` de Odoo)
2. Selecciona el certificado en el formulario de empresa (Facturacion Electronica)
3. Presiona **"Enviar Certificado a API"** → envia PEM a la API
4. La API lo almacena en su DB y lo usa para firmar y enviar a DIAN

** Campos en `res.company`:**
- `certificate_id` → Many2one a `certificate.certificate` (scope=facturapi)
- `facturapi_company_id` → UUID de la empresa en FacturAPI
- `facturapi_api_key` → API key (UUID) de la empresa en FacturAPI

---

## Modulo Base: `connector_facturapi`

El modulo que todo lo conecta. Proporciona:

### Modelos
- **`facturapi.document`** — Tabla principal que registra cada documento enviado a DIAN. Campos: `document_type`, `document_key`, `cufe`, `cuds`, `qr_code`, `status_code`, etc.
- **`certificate`** — Hereda `certificate.certificate`, agrega scope `"facturapi"`

### Configuracion de empresa (`res.company`)
- Toggle de habilitacion FacturAPI
- URL y API key del backend
- Certificado (seleccion del modulo `certificate` de Odoo)

### EDI Format
- Crea el formato EDI `facturapi_invoice` via `data/edi_format_data.xml`
- `facturapi_edi_format.py` busca el formato correcto por codigo (`invoice`, `support_document`, etc.)

---

## Modulo FE: `connector_facturapi_fe`

### Funcionalidad
- Botones "Enviar a DIAN" y "Consultar estado" en facturas
- Wizard de envio (`account_move_send.py`)
- Secuencias de numeracion por rango de fechas (`ir_sequence_date_range.py`)
- Reporte PDF de factura electronica (`report/`)
- Toggle de habilitacion FE por empresa

### Botones en empresa
- **"Enviar Certificado a API"** — Sube el certificado PEM a la API
- **"Consultar Rangos"** — Obtiene rangos de numeracion de DIAN

### Campos en `account.move`
- `connector_cufe` — CUFE calculado
- `connector_qr_code` — QR en base64
- `connector_document_key` — Llave del documento en DIAN
- `connector_status_code` — Codigo de respuesta DIAN
- `connector_status_message` — Mensaje DIAN

---

## Modulo DS: `connector_facturapi_ds`

### Funcionalidad
- Documento Soporte en adquisiciones a sujetos excluidos de facturar
- Botones "Enviar DS a DIAN" y "Consultar estado"
- Wizard de envio
- Secuencias DS propias

### Diferencias clave con FE
| Aspecto | FE | DS |
|---------|----|----|
| ProfileID | `DIAN 2.1: facturacion` | `DIAN 2.1: documento soporte...` |
| CustomizationID | 104445 | 10 |
| TypeCode | 01 (venta) | 05 (DS proveedor no obligado) |
| Hash UUID | CUFE (SHA-384) | CUDS (SHA-384) |
| Supplier TaxScheme | `01` (IVA) | `ZZ` (No aplica) |
| Supplier TaxLevelCode | `O-23` | `O-23;O-47` |
| QR format | `NroFactura=...` | `N°DocSoporte=DS...` |

### Campos en `account.move`
- `connector_cuds` — CUDS calculado
- `connector_ds_qr_code` — QR DS en base64
- `connector_ds_document_key` — Llave DS en DIAN

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
- `account_edi.format` es la clase base para formatos EDI

---

## Infraestructura Docker Odoo

**Docker Compose:** `C:\Users\jupar\Documents\GitHub\juanparmer\compose.yaml`

| Container | Puerto | DB User/Pass/DB |
|-----------|--------|-----------------|
| `odoo-web-1` | 8069 | — |
| `odoo-db-1` | 5432 | `odoo`/`odoo`/`admin` |

### Montar modulos en Odoo
Los modulos se montan via volumes en el Docker de Odoo. Verificar que las rutas en `docker-compose.yml` apunten a `connector-facturapi/` correctamente.

### Instalar un modulo
```bash
# Via CLI:
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi --stop-after-init
```

---

## COMO PROBAR

### Verificar que los modulos estan instalados
```sql
SELECT name, state FROM ir_module_module WHERE name LIKE 'connector_facturapi%';
```

### Verificar configuracion de empresa
```sql
SELECT name, facturapi_company_id, facturapi_api_key FROM res_company WHERE facturapi_company_id IS NOT NULL;
```

---

## Pendiente

- [ ] Modulo DE (`connector_facturapi_de`) — Documento Equivalente
- [ ] Modulo NOM (`connector_facturapi_nom`) — usar OCA `payroll` como base
- [ ] Modulo RADIAN (`connector_facturapi_radian`) — modelo nuevo `facturapi.radian.event`
- [ ] Tests automatizados
- [ ] Reports para DS
