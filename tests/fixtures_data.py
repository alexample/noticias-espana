"""Titulares sintéticos (inventados) con distintas redacciones por medio.

Cada historia tiene una etiqueta; el test comprueba que el algoritmo
reconstruye exactamente esos grupos. Incluye trampas: historias distintas
que comparten protagonista (Sánchez, Real Madrid, Valencia).
"""

STORIES = {
    "dana": [
        ("El País", "La Aemet activa la alerta roja por lluvias torrenciales en Valencia",
         "La Agencia Estatal de Meteorología prevé acumulados de más de 180 litros en la Comunitat Valenciana."),
        ("El Mundo", "Alerta roja en Valencia: la Aemet avisa de lluvias de hasta 180 litros",
         "Los municipios de la Ribera y la Safor suspenden las clases ante el temporal de lluvia."),
        ("RTVE", "Suspendidas las clases en la Ribera y la Safor por la alerta roja de lluvias",
         "La Generalitat pide evitar desplazamientos ante las lluvias torrenciales previstas por la Aemet."),
        ("20minutos", "Lluvias torrenciales en Valencia: la Generalitat pide no salir de casa",
         "La Aemet mantiene el aviso rojo en el litoral de Valencia con acumulados de 180 litros."),
        ("La Razón", "Temporal en Valencia: aviso rojo de la Aemet y colegios cerrados",
         "Las lluvias torrenciales obligan a suspender las clases en la Ribera."),
    ],
    "valencia_futbol": [
        ("ABC", "El Valencia destituye a su entrenador tras la derrota en Mestalla",
         "El club valencianista anuncia el cese del técnico después de encadenar cinco jornadas sin ganar."),
        ("El Español", "Mestalla dicta sentencia: el Valencia cesa a su entrenador",
         "Tras cinco jornadas sin ganar, el Valencia CF despide al técnico."),
        ("Marca", "Oficial: el Valencia CF despide a su técnico después de cinco jornadas sin ganar",
         "La directiva valencianista busca sustituto en el banquillo de Mestalla."),
    ],
    "presupuestos": [
        ("El País", "Sánchez presenta los Presupuestos Generales del Estado para 2027",
         "El Consejo de Ministros aprueba el proyecto de Presupuestos con un aumento del gasto en vivienda."),
        ("elDiario.es", "El Gobierno aprueba el proyecto de Presupuestos de 2027 con más gasto en vivienda",
         "Hacienda remitirá las cuentas al Congreso la próxima semana. Sánchez confía en los socios."),
        ("El Confidencial", "Los Presupuestos de 2027 llegan al Congreso: claves del gasto en vivienda",
         "Hacienda eleva un 12% la partida de vivienda en el proyecto aprobado por el Consejo de Ministros."),
        ("Europa Press", "Hacienda eleva un 12% la partida de vivienda en los Presupuestos de 2027",
         "El proyecto de Presupuestos Generales del Estado se debatirá en el Congreso."),
    ],
    "sanchez_otan": [
        ("El Mundo", "Sánchez viaja a Bruselas para la cumbre de la OTAN sobre gasto en defensa",
         "El presidente defenderá ante los aliados que España cumple sus compromisos militares."),
        ("La Vanguardia", "Cumbre de la OTAN: Sánchez defiende el gasto en defensa de España ante los aliados",
         "Los socios de la Alianza presionan para elevar el gasto militar al 3,5% del PIB."),
        ("ABC", "La OTAN presiona a España para subir el gasto militar al 3,5%",
         "Sánchez llega a Bruselas para la cumbre de la Alianza Atlántica."),
    ],
    "bce": [
        ("Expansión", "El BCE baja los tipos de interés un cuarto de punto hasta el 1,75%",
         "Lagarde abre la puerta a nuevas rebajas si la inflación sigue moderándose en la eurozona."),
        ("Cinco Días", "Lagarde recorta los tipos al 1,75% y deja abiertas nuevas bajadas",
         "El Banco Central Europeo reduce el precio del dinero por la moderación de la inflación."),
        ("El Economista", "El Euríbor cae tras la rebaja de tipos del BCE: qué pasa con tu hipoteca",
         "El Banco Central Europeo sitúa los tipos en el 1,75%."),
    ],
    "madrid_champions": [
        ("Marca", "El Real Madrid golea al Bayern y se clasifica para cuartos de la Champions",
         "Mbappé firma un doblete en el Bernabéu en una noche de Champions."),
        ("AS", "Doblete de Mbappé: el Madrid arrolla al Bayern en el Bernabéu",
         "Los blancos sellan el pase a cuartos de final de la Champions League."),
        ("Mundo Deportivo", "El Madrid pasa a cuartos de la Champions tras golear al Bayern",
         "Mbappé lideró la goleada blanca en el Bernabéu."),
    ],
    "madrid_lesion": [
        ("AS", "Lesión de Courtois: el Real Madrid confirma una rotura de fibras",
         "El portero belga estará de baja unas tres semanas, según el parte médico del club."),
        ("Marca", "Courtois, tres semanas de baja por una rotura de fibras",
         "El parte médico del Real Madrid confirma la lesión del guardameta belga."),
    ],
    # historias sueltas (un solo medio)
    "solo_1": [("Heraldo", "Zaragoza inaugura el nuevo tranvía hasta el barrio de Valdespartera",
                "La ampliación de la línea suma cuatro paradas.")],
    "solo_2": [("La Voz de Galicia", "Vigo enciende las luces de Navidad con dos semanas de antelación",
                "El alcalde Abel Caballero presume de un récord de bombillas LED.")],
    "solo_3": [("El Correo", "Bilbao aprueba la zona de bajas emisiones para 2027",
                "El Ayuntamiento restringirá el acceso de vehículos sin etiqueta al centro.")],
}
