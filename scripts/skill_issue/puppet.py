"""Pose solver: turns high-level pose specs into baked armature keyframes.

A pose spec is a dict in *character space* (armature space, character facing
-Y, left = +X):

    hips      : (offset Vector, (pitch, twist, side))   FK + translation
    spine/chest/neck/head : (pitch, twist, side) radians, bone-local
    clav.L/R  : (pitch, twist, side)
    arm.L/R   : dict(wrist=Vector, pole=Vector, fdir=Vector|None, palm=Vector|None)
    fingers.L/R: dict(index=(c1, c2), middle=..., ring=..., pinky=..., thumb=(c1, c2))
    leg.L/R   : dict(ankle=Vector, pole=Vector, toe=Vector|None)

Arms and legs use analytic two-bone IK. The result is converted into each
bone's matrix_basis and baked as location + quaternion f-curves (one key
per frame), so the final animation is ordinary, inspectable Blender data.
"""

import math

from mathutils import Matrix, Quaternion, Vector

from . import bl_util as U

SPINE = ["hips", "spine", "chest", "neck", "head"]
DIGITS = ["index", "middle", "ring", "pinky", "thumb"]


def _rot(euler_xyz):
    from mathutils import Euler
    return Euler(euler_xyz, 'XYZ').to_matrix().to_4x4()


class Solver:
    def __init__(self, ch):
        self.ch = ch
        self.R = ch.rest
        self.Rinv = {k: v.inverted() for k, v in self.R.items()}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in ch.rig.data.bones}
        self.len = {}
        for side in ("L", "R"):
            for a, b, c in (("upperarm", "forearm", "hand"), ("thigh", "shin", "foot")):
                pa = self.R[f"{a}.{side}"].translation
                pb = self.R[f"{b}.{side}"].translation
                pc = self.R[f"{c}.{side}"].translation
                self.len[f"{a}.{side}"] = ((pb - pa).length, (pc - pb).length)

    # -- helpers -----------------------------------------------------------
    def fk(self, D, bone, euler=(0, 0, 0)):
        p = self.parent[bone]
        rel = self.Rinv[p] @ self.R[bone]
        return D[p] @ rel @ _rot(euler)

    def follow(self, D, bone):
        return self.fk(D, bone)

    def swing(self, bone, origin, direction):
        R = self.R[bone]
        q = (R.to_3x3() @ Vector((0, 1, 0))).rotation_difference(direction.normalized())
        M = q.to_matrix().to_4x4() @ R.to_3x3().to_4x4()
        M.translation = origin
        return M

    @staticmethod
    def two_bone(root, target, a, b, pole):
        d = target - root
        dist = max(1e-5, min(d.length, (a + b) * 0.9995))
        dirn = d.normalized()
        cos_a = (a * a + dist * dist - b * b) / (2 * a * dist)
        cos_a = max(-1.0, min(1.0, cos_a))
        sin_a = math.sqrt(1 - cos_a * cos_a)
        pv = pole - root
        perp = pv - dirn * pv.dot(dirn)
        if perp.length < 1e-6:
            perp = dirn.orthogonal()
        perp.normalize()
        elbow = root + dirn * (a * cos_a) + perp * (a * sin_a)
        end = root + dirn * dist
        return elbow, end

    def frame(self, origin, ydir, xdir):
        y = ydir.normalized()
        x = (xdir - y * xdir.dot(y)).normalized()
        z = x.cross(y)
        M = Matrix((x, y, z)).transposed().to_4x4()
        M.translation = origin
        return M

    # -- solve -------------------------------------------------------------
    def solve(self, P):
        D = {}
        D["root"] = self.R["root"].copy()
        off, he = P.get("hips", (Vector((0, 0, 0)), (0, 0, 0)))
        hips = self.fk(D, "hips", he)
        hips.translation += off
        D["hips"] = hips
        for b in SPINE[1:]:
            D[b] = self.fk(D, b, P.get(b, (0, 0, 0)))
        for side, s in (("L", 1.0), ("R", -1.0)):
            D[f"clavicle.{side}"] = self.fk(D, f"clavicle.{side}", P.get(f"clav.{side}", (0, 0, 0)))
            # arm
            arm = P.get(f"arm.{side}")
            ub, fb, hb = f"upperarm.{side}", f"forearm.{side}", f"hand.{side}"
            shoulder = (D[f"clavicle.{side}"] @ self.Rinv[f"clavicle.{side}"] @ self.R[ub]).translation
            if arm:
                a, b = self.len[ub]
                elbow, wrist = self.two_bone(shoulder, arm["wrist"], a, b, arm["pole"])
                D[ub] = self.swing(ub, shoulder, elbow - shoulder)
                D[fb] = self.swing(fb, elbow, wrist - elbow)
                if arm.get("fdir") is not None:
                    D[hb] = self.frame(wrist, arm["fdir"], arm["palm"] * s)
                else:
                    D[hb] = self.follow(D, hb)
                    D[hb].translation = wrist
            else:
                for bb in (ub, fb, hb):
                    D[bb] = self.follow(D, bb)
            fingers = P.get(f"fingers.{side}", {})
            for dname in DIGITS:
                c1, c2 = fingers.get(dname, (0.15, 0.15))
                b1, b2 = f"{dname}1.{side}", f"{dname}2.{side}"
                if dname == "thumb":
                    D[b1] = self.fk(D, b1, (c1, 0, 0))
                    D[b2] = self.fk(D, b2, (c2, 0, 0))
                else:
                    D[b1] = self.fk(D, b1, (0, 0, -s * c1))
                    D[b2] = self.fk(D, b2, (0, 0, -s * c2))
            # leg
            leg = P.get(f"leg.{side}")
            tb, sb, ftb = f"thigh.{side}", f"shin.{side}", f"foot.{side}"
            hipj = (D["hips"] @ self.Rinv["hips"] @ self.R[tb]).translation
            if leg:
                a, b = self.len[tb]
                knee, ankle = self.two_bone(hipj, leg["ankle"], a, b, leg["pole"])
                D[tb] = self.swing(tb, hipj, knee - hipj)
                D[sb] = self.swing(sb, knee, ankle - knee)
                if leg.get("toe") is not None:
                    up = leg.get("up", Vector((0, 0, 1)))
                    ft = self.frame(ankle, leg["toe"], leg["toe"].cross(up))
                    # foot bone: y = toe, z = up  ->  x = y cross z
                    y = leg["toe"].normalized()
                    z = (up - y * up.dot(y)).normalized()
                    x = y.cross(z)
                    ft = Matrix((x, y, z)).transposed().to_4x4()
                    ft.translation = ankle
                    D[ftb] = ft
                else:
                    D[ftb] = self.follow(D, ftb)
                    D[ftb].translation = ankle
            else:
                for bb in (tb, sb, ftb):
                    D[bb] = self.follow(D, bb)
        return D

    def to_basis(self, D):
        out = {}
        for bone, Mb in D.items():
            p = self.parent[bone]
            if p is None:
                basis = self.Rinv[bone] @ Mb
            else:
                basis = (D[p] @ self.Rinv[p] @ self.R[bone]).inverted() @ Mb
            loc, rot, _ = basis.decompose()
            out[bone] = (loc, rot)
        return out


def bake_pose_track(ch, frames, pose_fn):
    """pose_fn(frame) -> pose spec. Bakes all bones. Returns per-frame D dicts."""
    solver = Solver(ch)
    rig = ch.rig
    series = {}
    Ds = []
    prev_q = {}
    for f in frames:
        D = solver.solve(pose_fn(f))
        Ds.append(D)
        basis = solver.to_basis(D)
        for bone, (loc, q) in basis.items():
            pq = prev_q.get(bone)
            if pq is not None and pq.dot(q) < 0:
                q = Quaternion((-q.w, -q.x, -q.y, -q.z))
            prev_q[bone] = q
            series.setdefault(bone, []).append((loc, q))
    for bone, vals in series.items():
        base = f'pose.bones["{bone}"]'
        for i in range(3):
            U.bake(rig, f"{base}.location", i, frames, [v[0][i] for v in vals])
        for i in range(4):
            U.bake(rig, f"{base}.rotation_quaternion", i, frames, [v[1][i] for v in vals])
    return Ds
