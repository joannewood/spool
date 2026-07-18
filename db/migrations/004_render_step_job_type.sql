-- Phase 03: STEP renders get their own job_type/queue lane so a slow CAD
-- tessellation never blocks quick STL/3MF renders queued behind it.
ALTER TYPE job_type ADD VALUE 'render_step';
