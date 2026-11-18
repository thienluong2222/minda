import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

function usePointer() {
  const pointer = useRef(new THREE.Vector2(0.5, 0.5));
  useEffect(() => {
    const move = (event: PointerEvent) =>
      pointer.current.set(
        event.clientX / innerWidth,
        1 - event.clientY / innerHeight,
      );
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, []);
  return pointer;
}

function Wave() {
  const pointer = usePointer();
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,
        uniforms: {
          time: { value: 0 },
          mouse: { value: new THREE.Vector2(0.5, 0.5) },
        },
        vertexShader:
          "varying vec2 vUv; void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}",
        fragmentShader: `varying vec2 vUv; uniform float time; uniform vec2 mouse;
      void main(){
        vec2 uv=vUv; float ink=0.;
        float interaction=exp(-length((uv-mouse)*vec2(1.,.7))*5.);
        for(int i=0;i<20;i++){
          float f=float(i); float y=.30+f*.018;
          y+=sin(uv.x*9.+time*.23+f*.12)*(.04+interaction*.045);
          y+=sin(uv.x*16.-time*.17+f*.15)*.014;
          float line=1.-smoothstep(.0007,.0022,abs(uv.y-y));
          ink+=line*.17;
        }
        float calm=.25+.75*smoothstep(.12,.4,abs(uv.x-.5));
        float fade=smoothstep(0.,.15,uv.x)*smoothstep(0.,.15,1.-uv.x);
        gl_FragColor=vec4(.247,.443,.349,min(ink,.34)*calm*fade);
      }`,
      }),
    [],
  );
  useEffect(() => () => material.dispose(), [material]);
  useFrame(({ clock }) => {
    material.uniforms.time.value = clock.getElapsedTime();
    material.uniforms.mouse.value.lerp(pointer.current, 0.045);
  });
  return (
    <mesh material={material}>
      <planeGeometry args={[2, 2]} />
    </mesh>
  );
}

function LayerObject() {
  const group = useRef<THREE.Group>(null);
  const pointer = usePointer();
  const { camera, size } = useThree();
  const plate = useMemo(() => {
    const w = 3.7,
      h = 2.5,
      r = 0.2,
      s = new THREE.Shape();
    s.moveTo(-w / 2 + r, -h / 2);
    s.lineTo(w / 2 - r, -h / 2);
    s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
    s.lineTo(w / 2, h / 2 - r);
    s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
    s.lineTo(-w / 2 + r, h / 2);
    s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
    s.lineTo(-w / 2, -h / 2 + r);
    s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
    return new THREE.ExtrudeGeometry(s, {
      depth: 0.05,
      bevelEnabled: true,
      bevelSegments: 2,
      steps: 1,
      bevelSize: 0.025,
      bevelThickness: 0.025,
    });
  }, []);
  const edges = useMemo(() => new THREE.EdgesGeometry(plate, 30), [plate]);
  useEffect(() => {
    camera.zoom = Math.min(size.width / 6.2, size.height / 5);
    camera.updateProjectionMatrix();
  }, [camera, size]);
  useEffect(
    () => () => {
      plate.dispose();
      edges.dispose();
    },
    [plate, edges],
  );
  useFrame(({ clock }, delta) => {
    if (!group.current) return;
    group.current.rotation.y = THREE.MathUtils.damp(
      group.current.rotation.y,
      (pointer.current.x - 0.5) * 0.2,
      3,
      delta,
    );
    group.current.position.y = Math.sin(clock.getElapsedTime() * 0.55) * 0.035;
  });
  return (
    <group ref={group}>
      {[0, 1, 2].map((i) => (
        <group
          key={i}
          position={[0, (i - 1) * 0.48, 0]}
          rotation={[-Math.PI / 2, 0, 0]}
        >
          <mesh geometry={plate}>
            <meshStandardMaterial
              color={i === 2 ? "#edf2e9" : "#e5ece1"}
              roughness={0.75}
              metalness={0.12}
            />
          </mesh>
          <lineSegments geometry={edges}>
            <lineBasicMaterial color="#3f7159" transparent opacity={0.25} />
          </lineSegments>
        </group>
      ))}
      {[0.65, 0.38, 0.23, 0.38, 0.65].map((height, i) => (
        <mesh key={i} position={[(i - 2) * 0.23, 0.67 + height / 2, 0]}>
          <capsuleGeometry args={[0.065, height, 4, 8]} />
          <meshStandardMaterial color="#3f7159" roughness={0.65} />
        </mesh>
      ))}
    </group>
  );
}

export default function Scene({
  kind,
  active,
}: {
  kind: "wave" | "layers";
  active: boolean;
}) {
  return (
    <Canvas
      className="minda-webgl"
      aria-hidden="true"
      orthographic={kind === "layers"}
      camera={kind === "layers" ? { position: [5, 4, 6], zoom: 60 } : undefined}
      dpr={[1, 1.5]}
      frameloop={active ? "always" : "never"}
      gl={{ alpha: true, antialias: true, powerPreference: "low-power" }}
      fallback={<span />}
    >
      {kind === "wave" ? (
        <Wave />
      ) : (
        <>
          <ambientLight intensity={1.7} />
          <directionalLight position={[2, 6, 4]} intensity={2.5} />
          <LayerObject />
        </>
      )}
    </Canvas>
  );
}
