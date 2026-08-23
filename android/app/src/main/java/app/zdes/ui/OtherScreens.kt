package app.zdes.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.zdes.data.PlaqueBrief

@Composable
fun ProcessingScreen(stage: String) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.height(20.dp))
        Text("$stage…", style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
fun CandidatesScreen(items: List<PlaqueBrief>, onPick: (Int) -> Unit, onNone: () -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
    ) {
        Text("Кажется, это…", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(4.dp))
        Text(
            "Не уверен до конца — выберите верного человека",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(16.dp))
        items.forEach { item ->
            val person = item.person
            CardRow(
                title = person?.fullName ?: "Без имени",
                subtitle = listOfNotNull(
                    person?.years,
                    item.distanceM?.let { "$it м отсюда" },
                ).joinToString(" · ").ifEmpty { null },
                onClick = { person?.id?.let(onPick) },
            )
        }
        Spacer(Modifier.height(12.dp))
        TextButton(onClick = onNone) { Text("Ничего из этого") }
    }
}

@Composable
fun NearbyScreen(items: List<PlaqueBrief>, note: String?, onPick: (Int) -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
    ) {
        Text("Таблички рядом", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(16.dp))
        if (items.isEmpty()) {
            Text(
                note ?: "Здесь мы пока ничего не знаем",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        items.forEach { item ->
            CardRow(
                title = item.person?.fullName ?: item.inscription.orEmpty().take(60),
                subtitle = listOfNotNull(
                    item.distanceM?.let { "$it м" },
                    item.person?.occupation,
                ).joinToString(" · ").ifEmpty { null },
                onClick = { item.person?.id?.let(onPick) },
            )
        }
        Spacer(Modifier.height(40.dp))
    }
}

/**
 * Экран неудачи с тремя выходами (FR-3.4). Пустой экран здесь недопустим:
 * это самый частый момент, когда пользователь бросает приложение.
 */
@Composable
fun FailureScreen(
    message: String,
    note: String?,
    onRetry: () -> Unit,
    onNearby: () -> Unit,
) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, style = MaterialTheme.typography.headlineMedium, textAlign = TextAlign.Center)
        note?.let {
            Spacer(Modifier.height(12.dp))
            Text(
                it,
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
            )
        }
        Spacer(Modifier.height(28.dp))
        Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) {
            Text("Снять ещё раз")
        }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onNearby, modifier = Modifier.fillMaxWidth()) {
            Text("Таблички рядом")
        }
    }
}
