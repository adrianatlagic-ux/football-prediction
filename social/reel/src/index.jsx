import { registerRoot, Composition } from 'remotion'
import { Reel, REEL_FRAMES } from './Reel.jsx'
import sample from './sample.json'

function Root() {
  return (
    <Composition
      id="Reel"
      component={Reel}
      durationInFrames={REEL_FRAMES}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={sample}
    />
  )
}

registerRoot(Root)
