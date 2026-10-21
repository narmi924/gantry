/**
 * Words that appear on a feed's picture, in that feed's language.
 *
 * The page around the broadcast is in English. Everything inside one feed's picture
 * (graphics, captions, names) is in that feed's own language, so no feed mixes two.
 */

export type Lang = 'en' | 'es' | 'pt' | 'fr' | 'ar' | 'hi' | 'id' | 'zh'

type Key =
  | 'you_asked' | 'player_of_the_match' | 'distance' | 'top_speed' | 'sprints' | 'passes' | 'goals_assists'
  | 'who_is_on_top' | 'match_stats' | 'possession' | 'shots' | 'xg' | 'pass_accuracy' | 'field_tilt' | 'ppda'
  | 'distance_km' | 'corners' | 'momentum' | 'highlights' | 'replay' | 'half_time' | 'full_time' | 'goal' | 'assisted_by'
  | 'lineups'

const STRINGS: Record<Lang, Record<Key, string>> = {
  en: {
    you_asked: 'You asked', player_of_the_match: 'Player of the match', distance: 'Distance', top_speed: 'Top speed',
    sprints: 'Sprints', passes: 'Passes', goals_assists: 'Goals, assists', who_is_on_top: 'Who is on top',
    match_stats: 'Match stats', possession: 'Possession', shots: 'Shots (on target)', xg: 'Expected goals',
    pass_accuracy: 'Pass accuracy', field_tilt: 'Final-third passes', ppda: 'Pressing (PPDA)', distance_km: 'Distance (km)',
    corners: 'Corners', momentum: 'Attack momentum, last {n} minutes', highlights: 'Highlights', replay: 'Replay',
    half_time: 'Half-time', full_time: 'Full-time', goal: 'Goal', assisted_by: 'assisted by {name}', lineups: 'Starting line-ups',
  },
  es: {
    you_asked: 'Tu pregunta', player_of_the_match: 'Jugador del partido', distance: 'Distancia', top_speed: 'Velocidad máxima',
    sprints: 'Sprints', passes: 'Pases', goals_assists: 'Goles, asistencias', who_is_on_top: 'Quién domina',
    match_stats: 'Estadísticas', possession: 'Posesión', shots: 'Tiros (a puerta)', xg: 'Goles esperados',
    pass_accuracy: 'Precisión de pase', field_tilt: 'Pases en el último tercio', ppda: 'Presión (PPDA)', distance_km: 'Distancia (km)',
    corners: 'Córners', momentum: 'Dominio ofensivo, últimos {n} minutos', highlights: 'Resumen', replay: 'Repetición',
    half_time: 'Descanso', full_time: 'Final', goal: 'Gol', assisted_by: 'asistencia de {name}', lineups: 'Alineaciones',
  },
  pt: {
    you_asked: 'Sua pergunta', player_of_the_match: 'Craque do jogo', distance: 'Distância', top_speed: 'Velocidade máxima',
    sprints: 'Sprints', passes: 'Passes', goals_assists: 'Gols, assistências', who_is_on_top: 'Quem domina',
    match_stats: 'Estatísticas', possession: 'Posse de bola', shots: 'Finalizações (no alvo)', xg: 'Gols esperados',
    pass_accuracy: 'Precisão de passe', field_tilt: 'Passes no terço final', ppda: 'Pressão (PPDA)', distance_km: 'Distância (km)',
    corners: 'Escanteios', momentum: 'Pressão ofensiva, últimos {n} minutos', highlights: 'Melhores momentos', replay: 'Replay',
    half_time: 'Intervalo', full_time: 'Fim de jogo', goal: 'Gol', assisted_by: 'assistência de {name}', lineups: 'Escalações',
  },
  fr: {
    you_asked: 'Votre question', player_of_the_match: 'Homme du match', distance: 'Distance', top_speed: 'Vitesse max.',
    sprints: 'Sprints', passes: 'Passes', goals_assists: 'Buts, passes décisives', who_is_on_top: 'Qui domine',
    match_stats: 'Statistiques', possession: 'Possession', shots: 'Tirs (cadrés)', xg: 'Buts attendus',
    pass_accuracy: 'Précision des passes', field_tilt: 'Passes dans le dernier tiers', ppda: 'Pressing (PPDA)', distance_km: 'Distance (km)',
    corners: 'Corners', momentum: 'Élan offensif, {n} dernières minutes', highlights: 'Résumé', replay: 'Ralenti',
    half_time: 'Mi-temps', full_time: 'Fin du match', goal: 'But', assisted_by: 'passe décisive de {name}', lineups: 'Compositions',
  },
  ar: {
    you_asked: 'سؤالك', player_of_the_match: 'رجل المباراة', distance: 'المسافة', top_speed: 'السرعة القصوى',
    sprints: 'الانطلاقات', passes: 'التمريرات', goals_assists: 'الأهداف، التمريرات الحاسمة', who_is_on_top: 'من يسيطر',
    match_stats: 'إحصائيات المباراة', possession: 'الاستحواذ', shots: 'التسديدات (على المرمى)', xg: 'الأهداف المتوقعة',
    pass_accuracy: 'دقة التمرير', field_tilt: 'التمريرات في الثلث الأخير', ppda: 'الضغط (PPDA)', distance_km: 'المسافة (كم)',
    corners: 'الركنيات', momentum: 'الزخم الهجومي، آخر {n} دقيقة', highlights: 'ملخص', replay: 'إعادة',
    half_time: 'نهاية الشوط الأول', full_time: 'نهاية المباراة', goal: 'هدف', assisted_by: 'بتمريرة من {name}', lineups: 'التشكيلة الأساسية',
  },
  hi: {
    you_asked: 'आपका सवाल', player_of_the_match: 'प्लेयर ऑफ़ द मैच', distance: 'दूरी', top_speed: 'टॉप स्पीड',
    sprints: 'स्प्रिंट', passes: 'पास', goals_assists: 'गोल, असिस्ट', who_is_on_top: 'किसका दबदबा',
    match_stats: 'मैच के आँकड़े', possession: 'गेंद पर कब्ज़ा', shots: 'शॉट (निशाने पर)', xg: 'अपेक्षित गोल',
    pass_accuracy: 'पास की सटीकता', field_tilt: 'आख़िरी तिहाई में पास', ppda: 'प्रेसिंग (PPDA)', distance_km: 'दूरी (किमी)',
    corners: 'कॉर्नर', momentum: 'हमले की लय, पिछले {n} मिनट', highlights: 'हाइलाइट्स', replay: 'रीप्ले',
    half_time: 'हाफ़-टाइम', full_time: 'फ़ुल-टाइम', goal: 'गोल', assisted_by: '{name} के पास पर', lineups: 'शुरुआती एकादश',
  },
  id: {
    you_asked: 'Pertanyaan Anda', player_of_the_match: 'Pemain terbaik', distance: 'Jarak', top_speed: 'Kecepatan tertinggi',
    sprints: 'Sprint', passes: 'Umpan', goals_assists: 'Gol, assist', who_is_on_top: 'Siapa yang unggul',
    match_stats: 'Statistik', possession: 'Penguasaan bola', shots: 'Tembakan (tepat sasaran)', xg: 'Gol harapan',
    pass_accuracy: 'Akurasi umpan', field_tilt: 'Umpan di sepertiga akhir', ppda: 'Tekanan (PPDA)', distance_km: 'Jarak (km)',
    corners: 'Sepak pojok', momentum: 'Momentum serangan, {n} menit terakhir', highlights: 'Sorotan', replay: 'Tayangan ulang',
    half_time: 'Turun minum', full_time: 'Pertandingan selesai', goal: 'Gol', assisted_by: 'umpan dari {name}', lineups: 'Susunan pemain',
  },
  zh: {
    you_asked: '你的问题', player_of_the_match: '全场最佳', distance: '跑动距离', top_speed: '最高速度',
    sprints: '冲刺', passes: '传球', goals_assists: '进球 / 助攻', who_is_on_top: '谁占上风',
    match_stats: '比赛数据', possession: '控球率', shots: '射门（射正）', xg: '预期进球',
    pass_accuracy: '传球成功率', field_tilt: '前场三区传球占比', ppda: '逼抢（PPDA）', distance_km: '跑动（公里）',
    corners: '角球', momentum: '进攻势头，最近 {n} 分钟', highlights: '集锦', replay: '回放',
    half_time: '半场结束', full_time: '全场结束', goal: '进球', assisted_by: '{name}助攻', lineups: '首发阵容',
  },
}

export const LANGUAGE_NAMES: Record<Lang, string> = {
  en: 'English', es: 'Spanish', pt: 'Portuguese', fr: 'French', ar: 'Arabic', hi: 'Hindi', id: 'Indonesian', zh: 'Chinese',
}

export const RTL = new Set<Lang>(['ar'])

export function t(lang: string, key: Key, vars: Record<string, string | number> = {}): string {
  const table = STRINGS[(lang in STRINGS ? lang : 'en') as Lang]
  return table[key].replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ''))
}

/** Names written in another script, per language, as the server's name sheet gives them. */
export type NameSheet = Record<string, { players: Record<string, { full: string; short: string }>; clubs: Record<string, { full: string; short: string }> }>

export function playerName(names: NameSheet, lang: string, id: string, english: string, short = false): string {
  const local = names[lang]?.players[id]
  if (local) return short ? local.short : local.full
  return short ? english.split(' ').slice(-1)[0] : english
}

export function clubName(names: NameSheet, lang: string, code: string, english: string, full = false): string {
  const local = names[lang]?.clubs[code]
  if (local) return full ? local.full : local.short
  return english
}
