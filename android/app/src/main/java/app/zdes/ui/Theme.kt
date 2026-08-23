package app.zdes.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Палитра городского камня: тёплый серый фон, латунный акцент.
// Сдержанно осознанно — таблички часто про трагедии (§11 ТЗ).
private val Brass = Color(0xFF8A6A3B)
private val Stone = Color(0xFF2B2A28)
private val Paper = Color(0xFFF6F3EE)

private val Light = lightColorScheme(
    primary = Brass, onPrimary = Color.White,
    background = Paper, onBackground = Stone,
    surface = Color.White, onSurface = Stone,
    surfaceVariant = Color(0xFFE8E3DA), onSurfaceVariant = Color(0xFF56534E),
)

private val Dark = darkColorScheme(
    primary = Color(0xFFD2AE76), onPrimary = Stone,
    background = Color(0xFF1A1917), onBackground = Paper,
    surface = Color(0xFF232220), onSurface = Paper,
    surfaceVariant = Color(0xFF33312D), onSurfaceVariant = Color(0xFFBDB7AD),
)

private val AppTypography = Typography(
    headlineMedium = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.SemiBold, lineHeight = 32.sp),
    titleMedium = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.SemiBold, lineHeight = 24.sp),
    bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 20.sp),
    labelMedium = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.6.sp),
)

@Composable
fun ZdesTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) Dark else Light,
        typography = AppTypography,
        content = content,
    )
}
