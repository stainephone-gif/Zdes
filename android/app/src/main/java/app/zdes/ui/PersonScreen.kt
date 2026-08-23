package app.zdes.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import app.zdes.data.PersonCard
import app.zdes.data.PlaqueBrief
import app.zdes.data.RelationItem

@Composable
fun PersonScreen(card: PersonCard, onRelation: (RelationItem) -> Unit) {
    val uriHandler = LocalUriHandler.current

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp),
    ) {
        Text(card.fullName, style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            listOfNotNull(card.years, card.occupation).joinToString(" · "),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        card.shortDescription?.let {
            Spacer(Modifier.height(20.dp))
            Text(it, style = MaterialTheme.typography.bodyLarge)
        }

        card.plaques.firstOrNull()?.let { plaque -> RelationToHouse(plaque) }

        if (card.contentLinks.isNotEmpty()) {
            SectionTitle("Читать · слушать · смотреть")
            card.contentLinks.forEach { link ->
                CardRow(
                    title = link.title ?: link.provider.orEmpty(),
                    subtitle = link.provider,
                    onClick = { uriHandler.openUri(link.url) },
                )
            }
        }

        if (card.works.isNotEmpty()) {
            SectionTitle("Что он построил")
            card.works.forEach { work ->
                CardRow(
                    title = work.title,
                    // Смысл блока — дойти, поэтому расстояние важнее года
                    subtitle = listOfNotNull(
                        work.distanceM?.let { "$it м отсюда" },
                        work.builtYear?.toString(),
                    ).joinToString(" · ").ifEmpty { null },
                )
            }
        }

        val relations = card.relations.filter { it.caption.isNotBlank() }
        if (relations.isNotEmpty()) {
            SectionTitle("Связи")
            relations.forEach { relation ->
                CardRow(title = relation.caption, onClick = { onRelation(relation) })
            }
        }

        // Источники видны всегда и не прячутся: это прямая работа с барьером
        // «а вдруг это придумано» из карты JTBD (FR-4.6)
        SectionTitle("Источники")
        if (card.sources.isEmpty()) {
            Text(
                "Источник не указан — запись не проверена",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.error,
            )
        } else {
            card.sources.forEach { source ->
                Text(
                    listOfNotNull(source.title, source.license).joinToString(" · "),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                    textDecoration = TextDecoration.Underline,
                    modifier = Modifier
                        .padding(vertical = 4.dp)
                        .clickable { uriHandler.openUri(source.url) },
                )
            }
        }
        Spacer(Modifier.height(40.dp))
    }
}

@Composable
private fun RelationToHouse(plaque: PlaqueBrief) {
    val verb = when (plaque.relationType) {
        "lived" -> "Жил в этом доме"
        "worked" -> "Работал здесь"
        "born" -> "Здесь родился"
        "died" -> "Здесь умер"
        else -> "Связан с этим домом"
    }
    Spacer(Modifier.height(16.dp))
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(verb, style = MaterialTheme.typography.titleMedium)
            plaque.relationYears?.let {
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
            plaque.inscription?.let {
                Spacer(Modifier.height(8.dp))
                Text(
                    "«$it»",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
fun SectionTitle(text: String) {
    Spacer(Modifier.height(28.dp))
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(8.dp))
}

@Composable
fun CardRow(title: String, subtitle: String? = null, onClick: (() -> Unit)? = null) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge)
                subtitle?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}
