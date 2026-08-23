package app.zdes

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.activity.compose.BackHandler
import app.zdes.ui.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ZdesTheme { App() } }
    }
}

@Composable
fun App(vm: AppViewModel = viewModel()) {
    val stack by vm.stack.collectAsState()
    val screen = stack.last()

    BackHandler(enabled = stack.size > 1) { vm.back() }

    Box(
        Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .then(if (screen is Screen.Camera) Modifier else Modifier.systemBarsPadding()),
    ) {
        when (screen) {
            is Screen.Camera -> CameraScreen(
                onPhoto = vm::recognize,
                onNearby = vm::openNearby,
            )

            is Screen.Processing -> ProcessingScreen(screen.stage)

            is Screen.Candidates -> CandidatesScreen(
                items = screen.items,
                onPick = { vm.openPerson(it) },
                onNone = { vm.toCamera() },
            )

            is Screen.Person -> PersonScreen(
                card = screen.card,
                onRelation = { relation ->
                    // Пока умеем переходить только по связям к людям;
                    // карточка места (S5) — следующий шаг.
                    if (relation.toType == "person") vm.openPerson(relation.toId)
                },
            )

            is Screen.Nearby -> NearbyScreen(
                items = screen.items,
                note = screen.note,
                onPick = { vm.openPerson(it) },
            )

            is Screen.Failure -> FailureScreen(
                message = screen.message,
                note = screen.note,
                onRetry = vm::toCamera,
                onNearby = vm::openNearby,
            )
        }
    }
}
