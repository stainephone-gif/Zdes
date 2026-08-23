package app.zdes.ui

import android.app.Application
import android.provider.Settings
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.zdes.data.Api
import app.zdes.data.DeviceLocation
import app.zdes.data.PersonCard
import app.zdes.data.PlaqueBrief
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.security.MessageDigest

sealed interface Screen {
    data object Camera : Screen
    data class Processing(val stage: String) : Screen
    data class Candidates(val items: List<PlaqueBrief>) : Screen
    data class Person(val card: PersonCard) : Screen
    data class Nearby(val items: List<PlaqueBrief>, val note: String?) : Screen
    data class Failure(val message: String, val note: String?) : Screen
}

class AppViewModel(app: Application) : AndroidViewModel(app) {

    // Стек экранов, а не одиночное состояние: переход по связям — это цепочка,
    // и «назад» должно возвращать по ней, а не выбрасывать на камеру (FR-4.5).
    private val _stack = MutableStateFlow<List<Screen>>(listOf(Screen.Camera))
    val stack: StateFlow<List<Screen>> = _stack.asStateFlow()

    val current: Screen get() = _stack.value.last()

    private val deviceId: String by lazy {
        val raw = Settings.Secure.getString(
            getApplication<Application>().contentResolver, Settings.Secure.ANDROID_ID,
        ) ?: "unknown"
        // Идентификатор устройства не должен быть привязан к личности (§11 ТЗ)
        MessageDigest.getInstance("SHA-256").digest(raw.toByteArray())
            .joinToString("") { "%02x".format(it) }.take(32)
    }

    private fun push(screen: Screen) {
        _stack.value = _stack.value + screen
    }

    private fun replace(screen: Screen) {
        _stack.value = _stack.value.dropLast(1) + screen
    }

    fun back(): Boolean {
        if (_stack.value.size <= 1) return false
        _stack.value = _stack.value.dropLast(1)
        return true
    }

    fun toCamera() {
        _stack.value = listOf(Screen.Camera)
    }

    fun recognize(photo: ByteArray) {
        push(Screen.Processing("Читаю табличку"))
        viewModelScope.launch {
            val location = DeviceLocation.last(getApplication())
            runCatching {
                withContext(Dispatchers.IO) {
                    Api.recognize(photo, location?.latitude, location?.longitude, deviceId)
                }
            }.onSuccess { response ->
                when (response.status) {
                    "matched" -> {
                        val personId = response.candidates.firstOrNull()?.person?.id
                        if (personId == null) {
                            replace(Screen.Failure("Не смог прочитать табличку", response.coverageNote))
                        } else {
                            replace(Screen.Processing("Собираю материалы"))
                            openPerson(personId, replaceCurrent = true)
                        }
                    }
                    "ambiguous" -> replace(Screen.Candidates(response.candidates))
                    else -> replace(
                        Screen.Failure("Не смог прочитать табличку", response.coverageNote)
                    )
                }
            }.onFailure { error ->
                replace(Screen.Failure(error.message ?: "Сервер недоступен", null))
            }
        }
    }

    fun openPerson(personId: Int, replaceCurrent: Boolean = false) {
        if (!replaceCurrent) push(Screen.Processing("Открываю"))
        viewModelScope.launch {
            val location = DeviceLocation.last(getApplication())
            runCatching {
                withContext(Dispatchers.IO) {
                    Api.person(personId, location?.latitude, location?.longitude)
                }
            }.onSuccess { replace(Screen.Person(it)) }
                .onFailure { replace(Screen.Failure(it.message ?: "Не удалось открыть", null)) }
        }
    }

    fun openNearby() {
        push(Screen.Processing("Смотрю, что рядом"))
        viewModelScope.launch {
            val location = DeviceLocation.last(getApplication())
            if (location == null) {
                replace(Screen.Failure("Нужен доступ к местоположению", null))
                return@launch
            }
            runCatching {
                withContext(Dispatchers.IO) {
                    Api.nearby(location.latitude, location.longitude)
                }
            }.onSuccess { replace(Screen.Nearby(it.items, it.coverageNote)) }
                .onFailure { replace(Screen.Failure(it.message ?: "Сервер недоступен", null)) }
        }
    }
}
