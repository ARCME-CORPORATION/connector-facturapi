# connector-facturapi

Módulos Odoo 18 para facturación electrónica colombiana (DIAN) integrados vía [FacturAPI](https://facturapi.io).

## Estructura

```
connector_facturapi/          # Base: certificado, config empresa, formato EDI, modelo facturapi.document
connector_facturapi_data/     # Datos: tablas DIAN (medios_pago, responsable_fiscal, etc.)
connector_facturapi_fe/       # FE: Factura Electrónica (botones, wizard, secuencias, reportes)
connector_facturapi_ds/       # DS: Documento Soporte (adquisiciones a no obligados)
connector_facturapi_de/       # DE: Documento Equivalente (pendiente)
connector_facturapi_nom/      # NOM: Nomina Individual (pendiente)
connector_facturapi_radian/   # RADIAN: Eventos (pendiente)
```

### Dependencias entre módulos

```
connector_facturapi_data  (sin dependencias)
        │
connector_facturapi  (depende de: account, account_edi, certificate, account_edi_ubl_cii)
   │        │
   │   connector_facturapi_fe  (depende de: connector_facturapi, connector_facturapi_data, account_move_name_sequence)
   │        │
   │   connector_facturapi_ds  (depende de: connector_facturapi, connector_facturapi_data, connector_facturapi_fe)
```

## Requisitos

- Odoo 18
- Python 3.10+
- Docker (recomendado para Odoo)
- Backend FacturAPI corriendo (API key y URL)

## Instalación

### Via UI

1. Settings > Apps > Buscar "FacturAPI" > Instalar

### Via CLI

```bash
# Instalar módulo base
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi --stop-after-init

# Instalar con datos DIAN
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi_data --stop-after-init

# Instalar FE completo
docker exec -it odoo-web-1 odoo -d admin -i connector_facturapi_fe --stop-after-init
```

## Configuración

### 1. Datos de la empresa (Settings > FacturAPI)

| Campo | Descripción |
|-------|-------------|
| FacturAPI URL | URL del backend (ej: `http://host.docker.internal:8000`) |
| Company UUID | Identificador del tenant en FacturAPI |
| API Key | Clave de autenticación |
| Environment | `habilitacion` o `produccion` |

### 2. Credenciales DIAN

| Campo | Descripción |
|-------|-------------|
| Software ID | Identificador del software asignado por DIAN |
| Software PIN | PIN del software |
| Software DV | Dígito de verificación |
| Test Set ID | Identificador del set de pruebas (solo habilitación) |

### 3. Certificado digital

1. Subir certificado PFX/PKCS12 en Settings > Certificados
2. Asignarlo a la empresa en la pestaña de Facturación Electrónica

### 4. Habilitar FE / DS

En la ficha de la empresa (Settings > Companies > Edit), pestaña "Facturación Electrónica":
- Marcar **Facturación Electrónica** para habilitar FE
- Marcar **Documento Soporte** para habilitar DS

## Uso

### Factura Electrónica (FE)

1. Crear una factura de venta (`account.move`)
2. Confirmar la factura
3. Hacer clic en **"Send to DIAN"** en el header
4. Verificar estado con **"Check DIAN Status"**
5. El PDF se genera con el formato DIAN (QR, CUFE, etc.)

### Documento Soporte (DS)

1. Crear una factura de tipo "Documento Soporte"
2. Confirmar
3. Hacer clic en **"Send DS a DIAN"**
4. Verificar estado con **"Consultar estado"**

## Campos en `account.move`

### FE

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `connector_cufe` | Char | CUFE calculado |
| `connector_qr_code` | Text | QR en base64 |
| `connector_xml_signed` | Text | XML firmado |
| `connector_document_key` | Char | Llave del documento en DIAN |
| `connector_status_code` | Char | Código de respuesta DIAN |
| `connector_status_message` | Text | Mensaje DIAN |
| `connector_sequence_range_id` | Many2one | Rango de numeración DIAN |

### DS

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `connector_cuds` | Char | CUDS calculado |
| `connector_ds_qr_code` | Text | QR DS en base64 |
| `connector_ds_xml_signed` | Text | XML firmado DS |
| `connector_ds_document_key` | Char | Llave DS en DIAN |

## Modelos personalizados

| Modelo | Descripción |
|--------|-------------|
| `facturapi.document` | Registro de documentos enviados a DIAN |
| `connector.dian.uom` | Unidades de medida DIAN |
| `connector.dian.type.code` | Tipos de documento DIAN |
| `connector.dian.tax.type` | Tipos de impuesto DIAN |
| `connector.dian.payment.method` | Medios de pago DIAN |
| `connector.dian.responsibility` | Responsabilidades fiscales DIAN |

## Verificación

### Módulos instalados

```sql
SELECT name, state FROM ir_module_module WHERE name LIKE 'connector_facturapi%';
```

### Columnas en account_move

```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'account_move' AND column_name LIKE 'connector_%';
```

### Formatos EDI

```sql
SELECT code, name FROM ir_edi_format WHERE code LIKE 'facturapi%';
```

## Licencia

LGPL-3
