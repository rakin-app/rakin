> **BORRADOR: pendiente de revisión por abogado.** 16 de noviembre de 2026.

# Textos legales de Rakin

Borradores escritos para las primeras academias, que son conocidas y entran a una beta gratuita. Un borrador razonable es mejor que nada mientras un abogado los revisa. Se basan en la [investigación legal](../legal-research.md) (#381), que cita la ley N° 19.628 modificada por la ley N° 21.719. Cada cláusula que descansa en una de sus respuestas la enlaza.

**Marcas en el texto:**

- `[ABOGADO: …]`: un punto abierto para el abogado.
- `[PENDIENTE: …]`: algo que depende de una función aún no construida.
- **[entre corchetes]**: un dato que se completa: el nombre de la academia, su RUT, una ciudad.

## La Empresa, antes del lanzamiento

> **BORRADOR: hasta el lanzamiento.** Rakin está en etapa de prueba y todavía no se lanza oficialmente: no se vende ni se cobra el servicio. Mientras sea así, **la Empresa** de los Términos de encargo, **Rakin** como parte de los Términos de servicio y el responsable del aviso de Rakin son la persona que lleva el proyecto, con contacto en hola@rakin.app. Ningún texto lleva todavía una razón social, un RUT, un representante ni un domicilio para Rakin. Al lanzamiento, cada texto lleva esos datos en una versión nueva, que las academias firman de nuevo.

## Los documentos

| Documento | Qué es | Quién lo acepta | Cuándo |
| --- | --- | --- | --- |
| [Términos de encargo](terminos-de-encargo.md) | el contrato de encargo (DPA) del art. 15 bis: cómo trata Rakin los datos de los alumnos por cuenta de cada academia | el representante de la academia y la Empresa, firmando | antes de que los datos de la academia entren a Rakin, y de nuevo con cada versión nueva. La copia firmada queda en los archivos de la Empresa; la versión y la fecha, en Rakin ([Crear una academia](../deploy.md#creating-a-gym)) |
| [Términos de servicio](terminos-de-servicio.md) | el contrato del servicio: beta gratuita, soporte, término; los términos pagados van en su sección 12 | los mismos, firmando, junto con los Términos de encargo | igual |
| [Aviso de privacidad de cada academia](aviso-de-privacidad-gimnasio.md) | lo que la academia, como responsable, informa a sus alumnos y apoderados (art. 14 ter) | nadie lo firma: la academia lo publica en `/privacidad` y lo enlaza desde la inscripción. Para los menores de 18 años, el apoderado da su consentimiento sobre él | cuando la academia completa Ajustes, antes de abrir su formulario de inscripción |
| [Aviso de privacidad de Rakin](aviso-de-privacidad-rakin.md) | lo que quien lleva Rakin, como responsable, informa sobre sus propios datos: quienes administran una academia, quienes le escriben, quienes visitan rakin.app | nadie lo firma: se publica | en `rakin.app/privacidad`, en la página de inicio (#343), y en `/privacidad` cuando la dirección no es de una academia |

## Lo que queda para el abogado

Las cinco confirmaciones de la [investigación](../legal-research.md#for-the-lawyer), cada una de sí o no:

1. **Menores de 18 años**: registrar el consentimiento del apoderado aunque la membresía sea un contrato, pidiéndolo como un acto separado de la membresía, porque el art. 12 presume que no es libre el consentimiento pedido dentro de un contrato que no lo necesita. La ley lo pide bajo los 14 años; la academia lo pide para todo menor de 18 (decisión del 16 de noviembre).
2. **Registros contables**: guardarlos 6 años con nombre y RUT aunque la persona pida que la borren.
3. **Forma de los Términos de encargo**:
   - (a) subencargados autorizados uno por uno;
   - (b) transferencias a Estados Unidos con las cláusulas de cada proveedor;
   - (c) 24 horas de la Empresa a la Academia, 72 de la Academia a la Agencia, y la Empresa puede avisar a los alumnos en nombre de la Academia.
4. **Identidad por RUT** compartida entre academias, descrita en los Términos de encargo, sin que la Empresa pase a ser responsable.
5. **Datos de salud** en un gimnasio (art. 16 bis): ¿están prohibidos aun con consentimiento? Rakin hoy los recoge (#384).

Más los puntos propios de estos textos, marcados `[ABOGADO: …]`:

- el límite de responsabilidad en la beta y su validez frente a la ley N° 19.496;
- si Cloudflare R2 debe fijar una región;
- la división entre lo que el equipo de una academia hace dentro de ella (de la academia) y su cuenta como cliente (de Rakin);
- cuánto tiempo guardar la facturación cuando Rakin cobre;
- la redacción del aviso de cada academia, que ya estaba pendiente con el abogado.

## Lo que estos textos prometen y el código aún no hace

Ningún texto se publica ni se firma como versión final hasta cerrar estos issues, o hasta quitarle al texto la promesa:

| Promesa | Dónde | Issue |
| --- | --- | --- |
| avisos y cobros al apoderado según la edad, no según el vínculo; el cambio de contacto a los 18 | aviso de cada academia | #368 |
| ver y exportar los propios datos | aviso de cada academia, derechos | #371 |
| eliminar a quien pagó, conservando 6 años la contabilidad | aviso de cada academia, retención | #372 |
| anonimizar a los 24 meses; eliminar los comprobantes a los 12 | aviso de cada academia, retención | #378 |
| copia completa y eliminación de una academia al terminar | Términos de encargo, cláusula 14 | #377 |
| aviso de vulneración en 24 horas, con quién y cómo | Términos de encargo, cláusula 12 | #369, #374 |
| menos datos a Sentry | Términos de encargo, Anexo A | #373 |
| reenviar en 1 día hábil lo que un alumno escriba a Rakin | Términos de encargo, cláusula 11; aviso de Rakin | #375 |
| ningún dato de salud: sin "Lesión" ni "Salud" como motivos; advertir al crear un campo sensible | Términos de encargo, cláusula 4; aviso de cada academia | #384, #376 |
| ensayar la restauración de respaldos | Términos de encargo, Anexo B | ops#2 |
| mostrar el aviso de Rakin en `/privacidad` sin academia | aviso de Rakin | (UX QA, run 1) |

## Cambios

| Fecha | Cambio |
| --- | --- |
| 2026-11-16 | Primeros borradores de los cuatro textos (#381). |
| 2026-11-16 | Decisión del dueño (fila 1 de la investigación): el consentimiento del apoderado se registra para todo alumno menor de 18 años, no solo bajo los 14, como un acto aparte de la membresía. 18 sigue siendo la edad del contacto y el pagador. El aviso de cada academia y los Términos de encargo dicen ahora «menor de 18 años» (#368). |
| 2026-11-16 | El registro de consentimiento (#370) cumple la promesa del aviso de cada academia: el apoderado de todo menor de 18 años da o retira su consentimiento, aparte de la membresía, en la inscripción o en su página, y queda registrado con la fecha, quién y la versión del aviso; los inscritos a mano o por planilla se lo piden en el correo de bienvenida. Sale de la lista de promesas pendientes. |
| 2026-11-18 | Los Términos de encargo tienen versión (2026-11-18, inicialmente 2026-11-16, en su encabezado). Ninguna academia se crea en Rakin sin registrar la versión que firmó y la fecha; las que ya existen, como Meta, registran su firma aparte. Una versión nueva, como al agregar un subencargado, se firma de nuevo (#367). |
| 2026-11-18 | Dónde están los datos (#430): el servidor y la base de datos están en Hetzner, en Ashburn, Virginia (Estados Unidos), y Sentry en su región de Estados Unidos, no en Alemania. Lo dicen el Anexo A de los Términos de encargo (versión 2026-11-18), el aviso de Rakin (versión 2) y el aviso de cada academia. Como el Anexo A nombra ahora al proveedor del servidor, que antes era un espacio por completar, y cambia el país de Sentry, cada academia firma la versión 2026-11-18, también la que firmó la anterior. El texto del aviso que muestra la aplicación no nombra países, así que no cambia. |
| 2026-11-18 | Antes del lanzamiento (#434): Rakin está en etapa de prueba, todavía sin lanzamiento oficial ni cobro, y ningún texto lleva aún una razón social para Rakin ([la Empresa, antes del lanzamiento](#la-empresa-antes-del-lanzamiento)). El aviso de Rakin (versión 3, vigente desde el 18 de noviembre de 2026) lo dice en «¿Quién es responsable?», tiene hola@rakin.app como contacto y nombra el proveedor de la casilla del proyecto a la que Cloudflare reenvía los correos. La página `rakin.app/privacidad` no se construye si le queda un dato `[entre corchetes]` sin completar. |
| 2026-11-18 | Dos servidores (#464): el actual, en Hetzner en Ashburn, pasa a ser el de producción, con las direcciones `rakin.app`, y uno nuevo en Hetzner en Núremberg (Alemania) pasa a ser el de pruebas (staging). **Ningún texto cambia.** El de pruebas no guarda datos de ninguna academia ni de ningún alumno: solo los datos de ejemplo, y las cuentas y direcciones de correo del propio equipo de Rakin, que no son datos tratados por cuenta de una academia. Así, el Anexo A de los Términos de encargo (Hetzner, Ashburn) y los dos avisos de privacidad siguen siendo exactos: no hay un lugar nuevo donde se traten datos personales, ni un subencargado nuevo, ni una versión nueva, y ninguna academia firma de nuevo. Si alguna vez el de pruebas recibiera datos de una academia, eso cambiaría los textos primero. |
| 2026-11-19 | Sesiones (#491, #493): una sesión ya no dura 30 días fijos. Vence tras 35 días sin uso y, en todo caso, a los 180 días del ingreso, así que quien abre la aplicación una vez al mes no tiene que volver a ingresar. El Anexo B de los Términos de encargo lo dice ahora, en la versión 2026-11-19, que sale junto con ese cambio. Como el Anexo B es parte de lo firmado, cada academia firma la versión 2026-11-19, también Meta. Los links de acceso no cambian: 15 minutos si se piden, 7 días si van en un aviso. |
