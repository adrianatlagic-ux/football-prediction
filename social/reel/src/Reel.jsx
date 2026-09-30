import { AbsoluteFill, Img, Sequence, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig, Easing } from 'remotion'
import { loadFont } from '@remotion/google-fonts/Inter'

const { fontFamily } = loadFont('normal', { weights: ['500', '700', '900'] })

const BG = '#0a0e1a'
const INK = '#f1f5f9'
const MUTED = '#94a3b8'
const ACCENT = '#4ade80'

// Scene lengths in frames at 30 fps: hook, probabilities, stats, score, call to action.
const SCENES = [75, 120, 105, 90, 75]
export const REEL_FRAMES = SCENES.reduce((a, b) => a + b, 0)

const pct = p => `${Math.round(p * 100)}%`

function useIn(delay = 0, damping = 14) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return spring({ frame: frame - delay, fps, config: { damping } })
}

function Badge({ iso, crest, size = 220 }) {
  const src = crest || `https://flagcdn.com/w640/${iso}.png`
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', overflow: 'hidden',
      boxShadow: '0 0 0 6px rgba(255,255,255,0.12), 0 20px 60px rgba(0,0,0,0.5)',
      background: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <Img src={src} style={crest
        ? { width: '72%', height: '72%', objectFit: 'contain' }
        : { width: '100%', height: '100%', objectFit: 'cover' }} />
    </div>
  )
}

function Header({ competition, kickoff }) {
  return (
    <div style={{ position: 'absolute', top: 150, width: '100%', textAlign: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18 }}>
        <Img src={staticFile('goaliq.svg')} style={{ width: 64, height: 64 }} />
        <span style={{ fontSize: 48, fontWeight: 900 }}>Goal<span style={{ color: ACCENT }}>IQ</span></span>
        <span style={{ fontSize: 30, fontWeight: 700, color: ACCENT, letterSpacing: 3, textTransform: 'uppercase', marginLeft: 8 }}>KI-Prognose</span>
      </div>
      <div style={{ fontSize: 34, fontWeight: 500, color: MUTED, marginTop: 12 }}>
        {competition} · {kickoff}
      </div>
    </div>
  )
}

function Hook({ home, away, homeIso, awayIso, homeCrest, awayCrest }) {
  const l = useIn(0)
  const r = useIn(6)
  const vs = useIn(14, 10)
  const q = useIn(26)
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 60 }}>
        <div style={{ transform: `translateX(${(1 - l) * -500}px)`, textAlign: 'center' }}>
          <Badge iso={homeIso} crest={homeCrest} />
          <div style={{ fontSize: 50, fontWeight: 900, marginTop: 30, width: 320 }}>{home}</div>
        </div>
        <div style={{ fontSize: 70, fontWeight: 900, color: MUTED, transform: `scale(${vs})` }}>vs</div>
        <div style={{ transform: `translateX(${(1 - r) * 500}px)`, textAlign: 'center' }}>
          <Badge iso={awayIso} crest={awayCrest} />
          <div style={{ fontSize: 50, fontWeight: 900, marginTop: 30, width: 320 }}>{away}</div>
        </div>
      </div>
      <div style={{
        position: 'absolute', bottom: 430, width: 900, textAlign: 'center',
        fontSize: 64, fontWeight: 900, lineHeight: 1.15, opacity: q, transform: `translateY(${(1 - q) * 40}px)`,
      }}>
        Wer gewinnt? <span style={{ color: ACCENT }}>Die KI</span> hat es durchgerechnet.
      </div>
    </AbsoluteFill>
  )
}

function ProbBar({ label, value, color, delay, highlight }) {
  const frame = useCurrentFrame()
  const t = interpolate(frame - delay, [0, 40], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic),
  })
  const shown = value * t
  return (
    <div style={{ marginBottom: 70, opacity: interpolate(frame - delay, [0, 8], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }) }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 18 }}>
        <span style={{ fontSize: 52, fontWeight: 700 }}>{label}</span>
        <span style={{ fontSize: 88, fontWeight: 900, color: highlight ? ACCENT : INK }}>{pct(shown)}</span>
      </div>
      <div style={{ height: 44, borderRadius: 22, background: 'rgba(255,255,255,0.08)', overflow: 'hidden' }}>
        <div style={{ width: `${shown * 100}%`, height: '100%', borderRadius: 22, background: color }} />
      </div>
    </div>
  )
}

function Probabilities({ home, away, pHome, pDraw, pAway, homeColor, awayColor }) {
  const top = Math.max(pHome, pDraw, pAway)
  const title = useIn(0)
  return (
    <AbsoluteFill style={{ padding: '0 110px', justifyContent: 'center' }}>
      <div style={{ fontSize: 58, fontWeight: 900, marginBottom: 80, opacity: title }}>Siegwahrscheinlichkeit</div>
      <ProbBar label={home} value={pHome} color={homeColor} delay={8} highlight={pHome === top} />
      <ProbBar label="Unentschieden" value={pDraw} color="#64748b" delay={22} highlight={pDraw === top} />
      <ProbBar label={away} value={pAway} color={awayColor} delay={36} highlight={pAway === top} />
    </AbsoluteFill>
  )
}

function StatRow({ stat, delay, homeColor, awayColor }) {
  const s = useIn(delay)
  const total = stat.home + stat.away || 1
  const fmt = v => String(v).replace('.', ',') + (stat.suffix || '')
  return (
    <div style={{ marginBottom: 64, opacity: s, transform: `translateY(${(1 - s) * 50}px)` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span style={{ fontSize: 76, fontWeight: 900 }}>{fmt(stat.home)}</span>
        <span style={{ fontSize: 40, fontWeight: 700, color: MUTED }}>{stat.label}</span>
        <span style={{ fontSize: 76, fontWeight: 900 }}>{fmt(stat.away)}</span>
      </div>
      <div style={{ display: 'flex', height: 18, borderRadius: 9, overflow: 'hidden', marginTop: 14, gap: 6 }}>
        <div style={{ flex: stat.home / total * s, background: homeColor, borderRadius: 9 }} />
        <div style={{ flex: stat.away / total * s, background: awayColor, borderRadius: 9 }} />
        <div style={{ flex: 1 - s }} />
      </div>
    </div>
  )
}

function Stats({ stats, homeColor, awayColor, home, away }) {
  const title = useIn(0)
  return (
    <AbsoluteFill style={{ padding: '0 110px', justifyContent: 'center' }}>
      <div style={{ fontSize: 58, fontWeight: 900, marginBottom: 20, opacity: title }}>So läuft das Spiel laut KI</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 38, color: MUTED, fontWeight: 700, marginBottom: 60, opacity: title }}>
        <span>{home}</span><span>{away}</span>
      </div>
      {stats.map((st, i) => (
        <StatRow key={st.label} stat={st} delay={10 + i * 12} homeColor={homeColor} awayColor={awayColor} />
      ))}
    </AbsoluteFill>
  )
}

function Score({ score, scoreProb }) {
  const frame = useCurrentFrame()
  const pop = useIn(18, 8)
  const flash = interpolate(frame, [16, 20, 34], [0, 0.55, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  const sub = useIn(34)
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <AbsoluteFill style={{ background: ACCENT, opacity: flash }} />
      <div style={{ fontSize: 54, fontWeight: 700, color: MUTED, opacity: useIn(0) }}>Wahrscheinlichstes Ergebnis</div>
      <div style={{
        fontSize: 330, fontWeight: 900, letterSpacing: -8, lineHeight: 1, margin: '40px 0',
        transform: `scale(${pop})`, textShadow: `0 0 80px ${ACCENT}66`,
      }}>
        {score.replace(':', ' : ')}
      </div>
      <div style={{ fontSize: 44, fontWeight: 500, color: MUTED, opacity: sub, width: 820, textAlign: 'center', lineHeight: 1.3 }}>
        Nur {pct(scoreProb)} Wahrscheinlichkeit für genau dieses Ergebnis. Fußball bleibt Fußball.
      </div>
    </AbsoluteFill>
  )
}

function Cta({ site }) {
  const a = useIn(0)
  const b = useIn(12)
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '0 100px' }}>
      <div style={{ fontSize: 76, fontWeight: 900, lineHeight: 1.15, opacity: a, transform: `translateY(${(1 - a) * 40}px)` }}>
        Liegt die KI richtig?
      </div>
      <div style={{ fontSize: 50, fontWeight: 500, color: MUTED, marginTop: 30, opacity: a }}>
        Auflösung nach dem Abpfiff. Folgen, um es nicht zu verpassen.
      </div>
      <div style={{
        marginTop: 90, fontSize: 52, fontWeight: 900, color: BG, background: ACCENT,
        padding: '26px 56px', borderRadius: 60, transform: `scale(${b})`,
      }}>
        {site}
      </div>
    </AbsoluteFill>
  )
}

export function Reel(props) {
  let start = 0
  const at = i => { const from = start; start += SCENES[i]; return from }
  return (
    <AbsoluteFill style={{ background: `radial-gradient(circle at 50% 30%, #16213d 0%, ${BG} 65%)`, color: INK, fontFamily }}>
      <Header competition={props.competition} kickoff={props.kickoff} />
      <Sequence from={at(0)} durationInFrames={SCENES[0]}><Hook {...props} /></Sequence>
      <Sequence from={at(1)} durationInFrames={SCENES[1]}><Probabilities {...props} /></Sequence>
      <Sequence from={at(2)} durationInFrames={SCENES[2]}><Stats {...props} /></Sequence>
      <Sequence from={at(3)} durationInFrames={SCENES[3]}><Score {...props} /></Sequence>
      <Sequence from={at(4)} durationInFrames={SCENES[4]}><Cta {...props} /></Sequence>
      <div style={{ position: 'absolute', bottom: 380, width: '100%', textAlign: 'center', fontSize: 28, color: '#64748b' }}>
        Statistische Prognose – keine Garantie
      </div>
    </AbsoluteFill>
  )
}
